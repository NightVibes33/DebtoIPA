#!/usr/bin/env python3
"""Generate and compile audited stock-iOS compatibility adapters.

These adapters provide normal app-sandbox replacements for a deliberately
small set of common jailbreak support APIs. They do not emulate process
injection, root access, private entitlements, or unrestricted daemons.
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


SWIFT_PREFERENCES = r'''import Foundation

public final class DebToIPAPreferences: @unchecked Sendable {
    public static let shared = DebToIPAPreferences()
    private let defaults: UserDefaults

    public init(suiteName: String? = nil) {
        defaults = suiteName.flatMap(UserDefaults.init(suiteName:)) ?? .standard
    }

    public func register(defaults values: [String: Any]) { defaults.register(defaults: values) }
    public func object(forKey key: String) -> Any? { defaults.object(forKey: key) }
    public func string(forKey key: String) -> String? { defaults.string(forKey: key) }
    public func bool(forKey key: String) -> Bool { defaults.bool(forKey: key) }
    public func integer(forKey key: String) -> Int { defaults.integer(forKey: key) }
    public func set(_ value: Any?, forKey key: String) { defaults.set(value, forKey: key) }
    public func removeObject(forKey key: String) { defaults.removeObject(forKey: key) }
}
'''

SWIFT_PATHS = r'''import Foundation

public enum DebToIPASandboxPaths {
    private static let fm = FileManager.default

    public static func documents(_ suffix: String = "") -> URL {
        append(fm.urls(for: .documentDirectory, in: .userDomainMask)[0], suffix)
    }

    public static func applicationSupport(_ suffix: String = "") -> URL {
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? fm.createDirectory(at: base, withIntermediateDirectories: true)
        return append(base, suffix)
    }

    public static func caches(_ suffix: String = "") -> URL {
        append(fm.urls(for: .cachesDirectory, in: .userDomainMask)[0], suffix)
    }

    public static func mappedURL(forLegacyPath path: String) -> URL {
        let normalized = path.replacingOccurrences(of: "//", with: "/")
        let mappings: [(String, (String) -> URL)] = [
            ("/var/mobile/Documents", documents),
            ("/private/var/mobile/Documents", documents),
            ("/var/mobile/Library/Preferences", applicationSupport),
            ("/private/var/mobile/Library/Preferences", applicationSupport),
            ("/var/mobile/Library", applicationSupport),
            ("/private/var/mobile/Library", applicationSupport),
            ("/var/jb/var/mobile/Library", applicationSupport)
        ]
        for (prefix, resolver) in mappings where normalized.hasPrefix(prefix) {
            return resolver(String(normalized.dropFirst(prefix.count)))
        }
        return applicationSupport(normalized.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    private static func append(_ base: URL, _ suffix: String) -> URL {
        let clean = suffix.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return clean.isEmpty ? base : base.appendingPathComponent(clean)
    }
}

public enum DTICompat {
    public static var preferencesDirectory: URL { DebToIPASandboxPaths.applicationSupport() }
    public static var documentsDirectory: URL { DebToIPASandboxPaths.documents() }
}
'''

SWIFT_NOTIFICATIONS = r'''import Foundation

public enum DebToIPANotifications {
    public static func post(_ name: String, object: Any? = nil) {
        NotificationCenter.default.post(name: Notification.Name(name), object: object)
    }

    @discardableResult
    public static func observe(_ name: String, using block: @escaping @Sendable (Notification) -> Void) -> NSObjectProtocol {
        NotificationCenter.default.addObserver(forName: Notification.Name(name), object: nil, queue: .main, using: block)
    }
}
'''

SWIFT_BACKGROUND = r'''import BackgroundTasks
import Foundation
import UIKit

public final class DebToIPABackgroundCoordinator: @unchecked Sendable {
    public static let shared = DebToIPABackgroundCoordinator()
    public static let refreshIdentifier = "__BUNDLE_ID__.refresh"
    public static let processingIdentifier = "__BUNDLE_ID__.processing"
    private var registered = false

    public func register() {
        guard !registered else { return }
        registered = true
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.refreshIdentifier, using: nil) { task in
            guard let refresh = task as? BGAppRefreshTask else { task.setTaskCompleted(success: false); return }
            self.handle(refresh)
        }
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.processingIdentifier, using: nil) { task in
            guard let processing = task as? BGProcessingTask else { task.setTaskCompleted(success: false); return }
            self.handle(processing)
        }
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { _ in
            self.schedule()
        }
    }

    public func schedule(after seconds: TimeInterval = 15 * 60) {
        let refresh = BGAppRefreshTaskRequest(identifier: Self.refreshIdentifier)
        refresh.earliestBeginDate = Date(timeIntervalSinceNow: seconds)
        try? BGTaskScheduler.shared.submit(refresh)
    }

    private func handle(_ task: BGTask) {
        let operation = Task.detached(priority: .utility) {
            // Package source may observe this event and perform bounded work.
            DebToIPANotifications.post("DebToIPABackgroundWork")
        }
        task.expirationHandler = { operation.cancel() }
        Task {
            _ = await operation.result
            task.setTaskCompleted(success: !operation.isCancelled)
            self.schedule()
        }
    }
}

private let _debToIPABackgroundBootstrap: Void = {
    DebToIPABackgroundCoordinator.shared.register()
}()
'''

SWIFT_APP_INTENTS = r'''import AppIntents

@available(iOS 16.0, *)
public struct DebToIPARunActionIntent: AppIntent {
    public static var title: LocalizedStringResource = "Run App Action"
    public static var description = IntentDescription("Runs a bounded action inside the converted app sandbox.")

    public init() {}
    public func perform() async throws -> some IntentResult {
        DebToIPANotifications.post("DebToIPAAppIntent")
        return .result()
    }
}
'''

SWIFT_SETTINGS = r'''import SwiftUI

public struct DebToIPASettingsView: View {
    @AppStorage("enabled") private var enabled = true
    @AppStorage("refreshInterval") private var refreshInterval = 15

    public init() {}
    public var body: some View {
        Form {
            Toggle("Enabled", isOn: $enabled)
            Stepper("Refresh interval: \(refreshInterval) minutes", value: $refreshInterval, in: 5...120, step: 5)
            Section { Text("These settings replace a jailbreak preference bundle and are stored inside the app sandbox.") }
        }
        .navigationTitle("Settings")
    }
}
'''

SWIFT_DOCUMENT_PICKER = r'''import SwiftUI
import UIKit
import UniformTypeIdentifiers

public struct DebToIPADocumentPicker: UIViewControllerRepresentable {
    public let contentTypes: [UTType]
    public let allowsMultipleSelection: Bool
    public let onPick: ([URL]) -> Void

    public init(contentTypes: [UTType] = [.data], allowsMultipleSelection: Bool = true, onPick: @escaping ([URL]) -> Void) {
        self.contentTypes = contentTypes
        self.allowsMultipleSelection = allowsMultipleSelection
        self.onPick = onPick
    }
    public func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }
    public func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let controller = UIDocumentPickerViewController(forOpeningContentTypes: contentTypes, asCopy: false)
        controller.allowsMultipleSelection = allowsMultipleSelection
        controller.delegate = context.coordinator
        return controller
    }
    public func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}
    public final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: ([URL]) -> Void
        init(onPick: @escaping ([URL]) -> Void) { self.onPick = onPick }
        public func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) { onPick(urls) }
    }
}

public enum DebToIPASecurityScopedBookmarks {
    public static func bookmark(for url: URL) throws -> Data {
        try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
    }
    public static func resolve(_ data: Data) throws -> URL {
        var stale = false
        return try URL(resolvingBookmarkData: data, options: [], relativeTo: nil, bookmarkDataIsStale: &stale)
    }
}
'''

SWIFT_BACKGROUND_TRANSFER = r'''import Foundation

public final class DebToIPABackgroundTransfer: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    public static let shared = DebToIPABackgroundTransfer()
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.background(withIdentifier: "__BUNDLE_ID__.transfers")
        configuration.sessionSendsLaunchEvents = true
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()
    public func download(_ url: URL) { session.downloadTask(with: url).resume() }
    public func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        DebToIPANotifications.post("DebToIPABackgroundDownloadFinished", object: location)
    }
}
'''

SWIFT_PUSH = r'''import UserNotifications
import UIKit

public enum DebToIPAPushSync {
    public static func requestAuthorization() async throws -> Bool {
        try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
    }
    @MainActor public static func registerForRemoteNotifications() { UIApplication.shared.registerForRemoteNotifications() }
}
'''

SWIFT_URL_ROUTER = r'''import Foundation

public enum DebToIPAURLRouter {
    public static func route(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return false }
        DebToIPANotifications.post("DebToIPAURLRoute", object: ["host": components.host ?? "", "path": components.path])
        return true
    }
}
'''

SWIFT_LOCAL_PROXY = r'''import Foundation
import Network

public final class DebToIPALocalConnection: @unchecked Sendable {
    private let connection: NWConnection
    public init(host: NWEndpoint.Host, port: NWEndpoint.Port) { connection = NWConnection(host: host, port: port, using: .tcp) }
    public func start(queue: DispatchQueue = .global(qos: .utility)) { connection.start(queue: queue) }
    public func send(_ data: Data) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data, completion: .contentProcessed { error in
                if let error { continuation.resume(throwing: error) } else { continuation.resume(returning: ()) }
            })
        }
    }
    public func cancel() { connection.cancel() }
}
'''

SWIFT_NATIVE_TOOL = r'''import Foundation

public protocol DebToIPANativeTool: Sendable {
    associatedtype Input: Codable & Sendable
    associatedtype Output: Codable & Sendable
    func run(_ input: Input) async throws -> Output
}
public enum DebToIPAToolError: Error { case sourceImplementationRequired }
'''

SWIFT_STANDALONE_UI = r'''import SwiftUI

public struct DebToIPAStandaloneRootView<Content: View>: View {
    private let content: Content
    public init(@ViewBuilder content: () -> Content) { self.content = content() }
    public var body: some View {
    NavigationView { content.navigationTitle("__APP_NAME__") }
        .navigationViewStyle(StackNavigationViewStyle())
}
}
'''

NETWORK_EXTENSION_SOURCE = r'''import NetworkExtension

@objc(DebToIPAPacketTunnelProvider)
final class DebToIPAPacketTunnelProvider: NEPacketTunnelProvider {
    override func startTunnel(options: [String : NSObject]?, completionHandler: @escaping (Error?) -> Void) { completionHandler(nil) }
    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) { completionHandler() }
}
'''

FILE_PROVIDER_SOURCE = r'''import FileProvider

@objc(DebToIPAFileProviderExtension)
final class DebToIPAFileProviderExtension: NSFileProviderExtension {
    override func item(for identifier: NSFileProviderItemIdentifier) throws -> NSFileProviderItem { throw NSFileProviderError(.noSuchItem) }
    override func urlForItem(withPersistentIdentifier identifier: NSFileProviderItemIdentifier) -> URL? { nil }
    override func persistentIdentifierForItem(at url: URL) -> NSFileProviderItemIdentifier? { nil }
    override func providePlaceholder(at url: URL, completionHandler: @escaping (Error?) -> Void) { completionHandler(nil) }
    override func startProvidingItem(at url: URL, completionHandler: @escaping (Error?) -> Void) { completionHandler(nil) }
    override func itemChanged(at url: URL) {}
    override func stopProvidingItem(at url: URL) {}
}
'''

OBJC_HEADER = r'''#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface HBPreferences : NSObject
- (instancetype)initWithIdentifier:(NSString *)identifier;
- (void)registerDefaults:(NSDictionary *)defaults;
- (nullable id)objectForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
- (double)doubleForKey:(NSString *)key;
- (void)setObject:(nullable id)value forKey:(NSString *)key;
- (void)setBool:(BOOL)value forKey:(NSString *)key;
- (void)setInteger:(NSInteger)value forKey:(NSString *)key;
- (void)setDouble:(double)value forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
- (void)synchronize;
@end

FOUNDATION_EXPORT NSString *DebToIPAMapLegacyPath(NSString *path);
FOUNDATION_EXPORT void DebToIPAPostNotification(NSString *name);

NS_ASSUME_NONNULL_END
'''

OBJC_IMPLEMENTATION = r'''#import "HBPreferences.h"

@interface HBPreferences ()
@property(nonatomic, strong) NSUserDefaults *defaults;
@end

@implementation HBPreferences
- (instancetype)init { return [self initWithIdentifier:@"DebToIPA"]; }
- (instancetype)initWithIdentifier:(NSString *)identifier {
    self = [super init];
    if (self) {
        self.defaults = [[NSUserDefaults alloc] initWithSuiteName:identifier] ?: NSUserDefaults.standardUserDefaults;
    }
    return self;
}
- (void)registerDefaults:(NSDictionary *)defaults { [self.defaults registerDefaults:defaults]; }
- (id)objectForKey:(NSString *)key { return [self.defaults objectForKey:key]; }
- (BOOL)boolForKey:(NSString *)key { return [self.defaults boolForKey:key]; }
- (NSInteger)integerForKey:(NSString *)key { return [self.defaults integerForKey:key]; }
- (double)doubleForKey:(NSString *)key { return [self.defaults doubleForKey:key]; }
- (void)setObject:(id)value forKey:(NSString *)key { [self.defaults setObject:value forKey:key]; }
- (void)setBool:(BOOL)value forKey:(NSString *)key { [self.defaults setBool:value forKey:key]; }
- (void)setInteger:(NSInteger)value forKey:(NSString *)key { [self.defaults setInteger:value forKey:key]; }
- (void)setDouble:(double)value forKey:(NSString *)key { [self.defaults setDouble:value forKey:key]; }
- (void)removeObjectForKey:(NSString *)key { [self.defaults removeObjectForKey:key]; }
- (void)synchronize { [self.defaults synchronize]; }
@end

NSString *DebToIPAMapLegacyPath(NSString *path) {
    NSArray<NSArray *> *mappings = @[
        @[@"/private/var/mobile/Documents", @"Documents"],
        @[@"/var/mobile/Documents", @"Documents"],
        @[@"/private/var/mobile/Library/Preferences", @"Library/Application Support"],
        @[@"/var/mobile/Library/Preferences", @"Library/Application Support"],
        @[@"/private/var/mobile/Library", @"Library/Application Support"],
        @[@"/var/mobile/Library", @"Library/Application Support"],
        @[@"/var/jb/var/mobile/Library", @"Library/Application Support"],
    ];
    for (NSArray *entry in mappings) {
        NSString *prefix = entry[0];
        if ([path hasPrefix:prefix]) {
            NSString *suffix = [path substringFromIndex:prefix.length];
            return [NSHomeDirectory() stringByAppendingPathComponent:[entry[1] stringByAppendingString:suffix]];
        }
    }
    NSString *clean = [path stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"/"]];
    return [[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"] stringByAppendingPathComponent:clean];
}

void DebToIPAPostNotification(NSString *name) {
    [[NSNotificationCenter defaultCenter] postNotificationName:name object:nil];
}
'''

C_INTERPOSE = r'''#import "HBPreferences.h"
#include <Foundation/Foundation.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *map_path(const char *path) {
    if (!path) return nil;
    NSString *value = [NSString stringWithUTF8String:path];
    NSArray<NSString *> *prefixes = @[
        @"/var/mobile/Documents", @"/private/var/mobile/Documents",
        @"/var/mobile/Library", @"/private/var/mobile/Library",
        @"/var/jb/var/mobile/Library"
    ];
    for (NSString *prefix in prefixes) {
        if ([value hasPrefix:prefix]) return DebToIPAMapLegacyPath(value);
    }
    return nil;
}

static int replacement_open(const char *path, int flags, ...) {
    static int (*original_open)(const char *, int, ...) = NULL;
    if (!original_open) original_open = dlsym(RTLD_NEXT, "open");
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list args; va_start(args, flags); mode = (mode_t)va_arg(args, int); va_end(args); }
    NSString *mapped = map_path(path);
    const char *actual = mapped ? mapped.fileSystemRepresentation : path;
    return (flags & O_CREAT) ? original_open(actual, flags, mode) : original_open(actual, flags);
}

static FILE *replacement_fopen(const char *path, const char *mode) {
    static FILE *(*original_fopen)(const char *, const char *) = NULL;
    if (!original_fopen) original_fopen = dlsym(RTLD_NEXT, "fopen");
    NSString *mapped = map_path(path);
    return original_fopen(mapped ? mapped.fileSystemRepresentation : path, mode);
}

static int replacement_stat(const char *path, struct stat *buffer) {
    static int (*original_stat)(const char *, struct stat *) = NULL;
    if (!original_stat) original_stat = dlsym(RTLD_NEXT, "stat");
    NSString *mapped = map_path(path);
    return original_stat(mapped ? mapped.fileSystemRepresentation : path, buffer);
}

#define DYLD_INTERPOSE(_replacement,_replacee) \
  __attribute__((used)) static struct { const void *replacement; const void *replacee; } \
  _interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = { \
    (const void *)(unsigned long)&_replacement, (const void *)(unsigned long)&_replacee \
  };

DYLD_INTERPOSE(replacement_open, open)
DYLD_INTERPOSE(replacement_fopen, fopen)
DYLD_INTERPOSE(replacement_stat, stat)
'''

WIDGET_SOURCE = r'''import SwiftUI
import WidgetKit

struct DebToIPAWidgetEntry: TimelineEntry { let date: Date }
struct DebToIPAWidgetProvider: TimelineProvider {
    func placeholder(in context: Context) -> DebToIPAWidgetEntry { .init(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (DebToIPAWidgetEntry) -> Void) { completion(.init(date: .now)) }
    func getTimeline(in context: Context, completion: @escaping (Timeline<DebToIPAWidgetEntry>) -> Void) {
        completion(Timeline(entries: [.init(date: .now)], policy: .after(.now.addingTimeInterval(900))))
    }
}
struct DebToIPAWidgetView: View {
    var entry: DebToIPAWidgetEntry
    var body: some View { VStack { Text("__APP_NAME__").font(.headline); Text("Open the app for full controls").font(.caption) } }
}
@main struct DebToIPAWidgetBundle: WidgetBundle {
    var body: some Widget { DebToIPAWidget() }
}
struct DebToIPAWidget: Widget {
    let kind = "__BUNDLE_ID__.widget"
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: DebToIPAWidgetProvider()) { DebToIPAWidgetView(entry: $0) }
            .configurationDisplayName("__APP_NAME__")
            .description("A stock-iOS replacement for glanceable jailbreak UI.")
    }
}
'''

SHARE_SOURCE = r'''import UIKit
import UniformTypeIdentifiers

@objc(DebToIPAShareViewController)
final class DebToIPAShareViewController: UIViewController {
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        let items = extensionContext?.inputItems.compactMap { $0 as? NSExtensionItem } ?? []
        let defaults = UserDefaults(suiteName: "__APP_GROUP__")
        defaults?.set(items.count, forKey: "lastSharedItemCount")
        extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
    }
}
'''

SAFARI_HANDLER = r'''import Foundation
import SafariServices

@objc(SafariWebExtensionHandler)
final class SafariWebExtensionHandler: NSObject, NSExtensionRequestHandling {
    func beginRequest(with context: NSExtensionContext) {
        let response = NSExtensionItem()
        if let input = context.inputItems.first as? NSExtensionItem,
           let message = input.userInfo?[SFExtensionMessageKey] {
            response.userInfo = [SFExtensionMessageKey: message]
        }
        context.completeRequest(returningItems: [response], completionHandler: nil)
    }
}
'''

CONTENT_BLOCKER_HANDLER = r'''import Foundation

@objc(ContentBlockerRequestHandler)
final class ContentBlockerRequestHandler: NSObject, NSExtensionRequestHandling {
    func beginRequest(with context: NSExtensionContext) {
        guard let url = Bundle.main.url(forResource: "blockerList", withExtension: "json") else {
            context.cancelRequest(withError: CocoaError(.fileNoSuchFile))
            return
        }
        let item = NSExtensionItem()
        item.attachments = [NSItemProvider(contentsOf: url)!]
        context.completeRequest(returningItems: [item], completionHandler: nil)
    }
}
'''

SAFARI_MANIFEST = {
    "manifest_version": 2,
    "name": "DebToIPA Safari Alternative",
    "version": "1.0",
    "description": "Generated public-API Safari alternative.",
    "permissions": [],
    "content_scripts": [],
}

COMPANION_PACKAGE = {
    "name": "debtoipa-companion-service",
    "version": "1.0.0",
    "private": True,
    "scripts": {"dev": "vercel dev", "typecheck": "tsc --noEmit"},
    "devDependencies": {"@vercel/node": "latest", "typescript": "latest"},
}

COMPANION_API = r'''import type { VercelRequest, VercelResponse } from '@vercel/node';

export default async function handler(request: VercelRequest, response: VercelResponse) {
  if (request.method !== 'POST') return response.status(405).json({ error: 'POST required' });
  const body = typeof request.body === 'object' && request.body ? request.body : {};
  // Replace this bounded example with package-specific, lawful server-side work.
  return response.status(200).json({ ok: true, acceptedAt: new Date().toISOString(), input: body });
}
'''

COMPANION_CLIENT = r'''import Foundation

public struct DebToIPACompanionClient: Sendable {
    public let endpoint: URL
    public init(endpoint: URL) { self.endpoint = endpoint }
    public func perform(payload: [String: String]) async throws -> Data {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else { throw URLError(.badServerResponse) }
        return data
    }
}
'''


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_adapter_sdk(
    destination: Path,
    *,
    bundle_id: str,
    app_name: str,
    alternatives: Iterable[str],
    app_group: str | None = None,
) -> dict[str, Any]:
    alternatives_set = set(alternatives)
    destination.mkdir(parents=True, exist_ok=True)
    swift = destination / "Swift"
    objc = destination / "ObjectiveC"
    generated: list[str] = []

    swift_files = {
        "PreferencesAdapter.swift": SWIFT_PREFERENCES,
        "SandboxPathAdapter.swift": SWIFT_PATHS,
        "NotificationAdapter.swift": SWIFT_NOTIFICATIONS,
    }
    if "background-task" in alternatives_set or "background-transfer" in alternatives_set:
        swift_files["BackgroundTaskAdapter.swift"] = SWIFT_BACKGROUND.replace("__BUNDLE_ID__", bundle_id)
    if "background-transfer" in alternatives_set:
        swift_files["BackgroundTransferAdapter.swift"] = SWIFT_BACKGROUND_TRANSFER.replace("__BUNDLE_ID__", bundle_id)
    if "push-notifications" in alternatives_set:
        swift_files["PushSyncAdapter.swift"] = SWIFT_PUSH
    if "app-intents" in alternatives_set:
        swift_files["AppIntentAdapter.swift"] = SWIFT_APP_INTENTS
    if "settings-screen" in alternatives_set:
        swift_files["SettingsView.swift"] = SWIFT_SETTINGS
    if "document-picker" in alternatives_set:
        swift_files["DocumentPickerAdapter.swift"] = SWIFT_DOCUMENT_PICKER
    if "url-schemes" in alternatives_set:
        swift_files["URLRouter.swift"] = SWIFT_URL_ROUTER
    if "local-proxy" in alternatives_set:
        swift_files["LocalConnection.swift"] = SWIFT_LOCAL_PROXY
    if "native-library" in alternatives_set:
        swift_files["NativeTool.swift"] = SWIFT_NATIVE_TOOL
    if "standalone-ui" in alternatives_set:
        swift_files["StandaloneRootView.swift"] = SWIFT_STANDALONE_UI.replace("__APP_NAME__", app_name)
    if "companion-service" in alternatives_set:
        swift_files["CompanionClient.swift"] = COMPANION_CLIENT
    for name, content in swift_files.items():
        _write(swift / name, content)
        generated.append(str((swift / name).relative_to(destination)))

    _write(objc / "HBPreferences.h", OBJC_HEADER)
    _write(objc / "HBPreferences.m", OBJC_IMPLEMENTATION)
    _write(objc / "SandboxInterpose.m", C_INTERPOSE)
    generated.extend(["ObjectiveC/HBPreferences.h", "ObjectiveC/HBPreferences.m", "ObjectiveC/SandboxInterpose.m"])

    extension_kinds: list[str] = []
    if "widget-extension" in alternatives_set:
        _write(destination / "Extensions/Widget/Widget.swift", WIDGET_SOURCE.replace("__APP_NAME__", app_name).replace("__BUNDLE_ID__", bundle_id))
        extension_kinds.append("widget")
    if "share-extension" in alternatives_set:
        group = app_group or f"group.{bundle_id}"
        _write(destination / "Extensions/Share/ShareViewController.swift", SHARE_SOURCE.replace("__APP_GROUP__", group))
        extension_kinds.append("share")
    if "safari-web-extension" in alternatives_set:
        _write(destination / "Extensions/Safari/SafariWebExtensionHandler.swift", SAFARI_HANDLER)
        _write(destination / "Extensions/Safari/manifest.json", json.dumps(SAFARI_MANIFEST, indent=2) + "\n")
        extension_kinds.append("safari")
    if "content-blocker" in alternatives_set:
        _write(destination / "Extensions/ContentBlocker/ContentBlockerRequestHandler.swift", CONTENT_BLOCKER_HANDLER)
        _write(destination / "Extensions/ContentBlocker/blockerList.json", "[]\n")
        extension_kinds.append("content-blocker")
    if "network-extension" in alternatives_set:
        _write(destination / "Extensions/Network/DebToIPAPacketTunnelProvider.swift", NETWORK_EXTENSION_SOURCE)
        extension_kinds.append("network")
    if "file-provider" in alternatives_set:
        _write(destination / "Extensions/FileProvider/DebToIPAFileProviderExtension.swift", FILE_PROVIDER_SOURCE)
        extension_kinds.append("file-provider")

    entitlements: dict[str, Any] = {}
    if app_group:
        entitlements["com.apple.security.application-groups"] = [app_group]
    if "push-notifications" in alternatives_set:
        entitlements["aps-environment"] = "development"
    if "network-extension" in alternatives_set:
        entitlements["com.apple.developer.networking.networkextension"] = ["packet-tunnel-provider"]
    if "file-provider" in alternatives_set:
        entitlements["com.apple.developer.fileprovider.testing-mode"] = True
    if entitlements:
        signing = destination / "Signing/Entitlements.plist"
        signing.parent.mkdir(parents=True, exist_ok=True)
        signing.write_bytes(plistlib.dumps(entitlements, fmt=plistlib.FMT_XML, sort_keys=True))
        generated.append("Signing/Entitlements.plist")

    if "companion-service" in alternatives_set:
        _write(destination / "CompanionService/package.json", json.dumps(COMPANION_PACKAGE, indent=2) + "\n")
        _write(destination / "CompanionService/api/task.ts", COMPANION_API)
        _write(destination / "CompanionService/tsconfig.json", json.dumps({"compilerOptions": {"strict": True, "target": "ES2022", "module": "NodeNext", "moduleResolution": "NodeNext"}}, indent=2) + "\n")
        _write(destination / "CompanionService/README.md", "# Generated companion service\n\nDeploy only package-specific, lawful server-side work. This service cannot reproduce root access, process injection, or private iOS entitlements.\n")

    manifest = {
        "schemaVersion": 1,
        "bundleIdentifier": bundle_id,
        "appName": app_name,
        "alternatives": sorted(alternatives_set),
        "generatedFiles": generated,
        "extensions": extension_kinds,
        "limitations": [
            "The adapters do not provide root access, process injection, private entitlements, kernel access, or continuous unrestricted execution.",
            "Generated extensions and background modes still require signing and any Apple-granted capabilities before installation or distribution.",
        ],
    }
    _write(destination / "AdapterManifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest


def build_binary_adapter_framework(
    sdk_root: Path,
    output_directory: Path,
    *,
    minimum_ios: str,
    install_name: str = "@rpath/DebToIPAAdapters.framework/DebToIPAAdapters",
) -> Path:
    if shutil.which("xcrun") is None:
        raise RuntimeError("Xcode command-line tools are required to compile the binary adapter framework.")
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    clang = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True).strip()
    framework = output_directory / "DebToIPAAdapters.framework"
    framework.mkdir(parents=True, exist_ok=True)
    binary = framework / "DebToIPAAdapters"
    sources = [
        sdk_root / "ObjectiveC/HBPreferences.m",
        sdk_root / "ObjectiveC/SandboxInterpose.m",
    ]
    command = [
        clang,
        "-target", f"arm64-apple-ios{minimum_ios}",
        "-isysroot", sdk,
        "-fobjc-arc",
        "-dynamiclib",
        "-install_name", install_name,
        "-Wl,-dead_strip",
        "-framework", "Foundation",
        "-framework", "UIKit",
        "-o", str(binary),
        *map(str, sources),
    ]
    subprocess.run(command, check=True)
    os.chmod(binary, 0o755)
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "DebToIPAAdapters",
        "CFBundleIdentifier": "app.debtoipa.adapters",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "DebToIPAAdapters",
        "CFBundlePackageType": "FMWK",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "MinimumOSVersion": minimum_ios,
    }
    (framework / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
    headers = framework / "Headers"
    headers.mkdir(exist_ok=True)
    shutil.copy2(sdk_root / "ObjectiveC/HBPreferences.h", headers / "HBPreferences.h")
    modules = framework / "Modules"
    modules.mkdir(exist_ok=True)
    (modules / "module.modulemap").write_text('framework module DebToIPAAdapters { umbrella header "HBPreferences.h" export * }\n', encoding="utf-8")
    return framework
