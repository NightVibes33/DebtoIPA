import Foundation

@MainActor
final class CompatibilityHostModel: ObservableObject {
    @Published private(set) var manifest: PortManifest?
    @Published private(set) var fileIndex = PortFileIndex(included: [], skipped: [])
    @Published private(set) var files: [PortFile] = []
    @Published private(set) var installState = "Preparing translated resources…"
    @Published var selectedFile: PortFile?
    @Published var selectedFileText = ""
    @Published var errorMessage: String?

    private let fileManager = FileManager.default

    init() {
        load()
    }

    var title: String {
        manifest?.name ?? "DebToIPA Compatibility Host"
    }

    var isFeatureComplete: Bool {
        manifest?.hostBuild?.featureComplete ?? false
    }

    var isLaunchable: Bool {
        manifest?.hostBuild?.launchable ?? true
    }

    var translatedCapabilities: [String] {
        manifest?.hostBuild?.translatedCapabilities
            ?? manifest?.capabilityPlan?.translatable
            ?? []
    }

    var redesignItems: [String] {
        manifest?.hostBuild?.requiresRedesign
            ?? manifest?.capabilityPlan?.requiresRedesign
            ?? []
    }

    var unavailableItems: [String] {
        manifest?.hostBuild?.notEmulatable
            ?? manifest?.capabilityPlan?.notEmulatable
            ?? []
    }

    var warning: String? {
        manifest?.hostBuild?.warning
    }

    var installedPayloadURL: URL? {
        guard let applicationSupport = try? fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ) else { return nil }
        return applicationSupport
            .appendingPathComponent("DebToIPA", isDirectory: true)
            .appendingPathComponent("PortPayload", isDirectory: true)
    }

    func load() {
        do {
            let decoder = JSONDecoder()
            guard let resourceRoot = Bundle.main.resourceURL?.appendingPathComponent("DebToIPA", isDirectory: true) else {
                throw HostError.missingBundleResources
            }

            let manifestURL = resourceRoot.appendingPathComponent("PortManifest.json")
            let manifestData = try Data(contentsOf: manifestURL)
            manifest = try decoder.decode(PortManifest.self, from: manifestData)

            let indexURL = resourceRoot.appendingPathComponent("PortFileIndex.json")
            if fileManager.fileExists(atPath: indexURL.path) {
                fileIndex = try decoder.decode(PortFileIndex.self, from: Data(contentsOf: indexURL))
            }

            try installBundledPayload(from: resourceRoot.appendingPathComponent("PortPayload", isDirectory: true))
            rebuildFileList()
            installState = files.isEmpty
                ? "The compatibility host is ready. No translated resource files were included."
                : "Installed \(files.count) translated resource file\(files.count == 1 ? "" : "s") inside the app container."
        } catch {
            installState = "Compatibility data could not be loaded."
            errorMessage = error.localizedDescription
        }
    }

    func preview(_ file: PortFile) {
        selectedFile = file
        do {
            let attributes = try fileManager.attributesOfItem(atPath: file.localURL.path)
            let size = (attributes[.size] as? NSNumber)?.intValue ?? 0
            guard size <= 1_500_000 else {
                selectedFileText = "This file is too large for the built-in preview. It remains available through Files sharing."
                return
            }
            let data = try Data(contentsOf: file.localURL)
            if let text = String(data: data, encoding: .utf8) {
                selectedFileText = text
            } else {
                selectedFileText = "Binary resource · \(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))"
            }
        } catch {
            selectedFileText = "Unable to preview this resource: \(error.localizedDescription)"
        }
    }

    func originalPathDescription(for file: PortFile) -> String {
        "/" + file.relativePath
    }

    private func installBundledPayload(from source: URL) throws {
        guard fileManager.fileExists(atPath: source.path) else { return }
        guard let destination = installedPayloadURL else { throw HostError.noApplicationSupport }
        let parent = destination.deletingLastPathComponent()
        try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }
        try fileManager.copyItem(at: source, to: destination)
    }

    private func rebuildFileList() {
        guard let root = installedPayloadURL else {
            files = []
            return
        }
        files = fileIndex.included.compactMap { relativePath in
            let local = root.appendingPathComponent(relativePath)
            guard fileManager.fileExists(atPath: local.path) else { return nil }
            let attributes = try? fileManager.attributesOfItem(atPath: local.path)
            let size = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
            return PortFile(relativePath: relativePath, size: size, localURL: local)
        }
        .sorted { $0.relativePath.localizedStandardCompare($1.relativePath) == .orderedAscending }
    }
}

private enum HostError: LocalizedError {
    case missingBundleResources
    case noApplicationSupport

    var errorDescription: String? {
        switch self {
        case .missingBundleResources:
            return "This IPA does not contain a DebToIPA compatibility manifest."
        case .noApplicationSupport:
            return "The app container could not create its compatibility storage directory."
        }
    }
}
