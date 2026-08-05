import Foundation

struct PortManifest: Decodable {
    let schemaVersion: Int?
    let name: String
    let bundleIdentifier: String?
    let minimumIOS: String?
    let sourceApp: String?
    let virtualPathMappings: [String: String]?
    let capabilityPlan: CapabilityPlan?
    let hostBuild: HostBuild?

    struct CapabilityPlan: Decodable {
        let translatable: [String]?
        let requiresRedesign: [String]?
        let notEmulatable: [String]?
    }

    struct HostBuild: Decodable {
        let schemaVersion: Int?
        let kind: String?
        let launchable: Bool
        let featureComplete: Bool
        let originalBinaryExecuted: Bool
        let includedResourceCount: Int?
        let skippedResourceCount: Int?
        let translatedCapabilities: [String]?
        let requiresRedesign: [String]?
        let notEmulatable: [String]?
        let originalBlockers: [String]?
        let warning: String?
    }
}

struct PortFileIndex: Decodable {
    let included: [String]
    let skipped: [SkippedFile]

    struct SkippedFile: Decodable, Identifiable {
        var id: String { path + reason }
        let path: String
        let reason: String
    }
}

struct PortFile: Identifiable, Hashable {
    var id: String { relativePath }
    let relativePath: String
    let size: Int64
    let localURL: URL
}
