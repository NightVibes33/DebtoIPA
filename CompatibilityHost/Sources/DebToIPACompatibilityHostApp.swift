import SwiftUI

@main
struct DebToIPACompatibilityHostApp: App {
    @StateObject private var model = CompatibilityHostModel()

    var body: some Scene {
        WindowGroup {
            CompatibilityRootView()
                .environmentObject(model)
        }
    }
}
