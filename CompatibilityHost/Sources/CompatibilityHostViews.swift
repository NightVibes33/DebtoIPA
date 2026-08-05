import SwiftUI

struct CompatibilityRootView: View {
    @EnvironmentObject private var model: CompatibilityHostModel

    var body: some View {
        TabView {
            NavigationView {
                OverviewView()
            }
            .tabItem { Label("Overview", systemImage: "sparkles") }

            NavigationView {
                FilesView()
            }
            .tabItem { Label("Files", systemImage: "folder") }

            NavigationView {
                DiagnosticsView()
            }
            .tabItem { Label("Port Status", systemImage: "checklist") }
        }
        .accentColor(.indigo)
        .alert("Compatibility Host", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "Unknown error")
        }
    }
}

private struct OverviewView: View {
    @EnvironmentObject private var model: CompatibilityHostModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(model.title)
                        .font(.system(size: 34, weight: .bold, design: .rounded))
                    Text(model.isFeatureComplete ? "Stock-iOS replacement" : "Launchable compatibility build")
                        .font(.headline)
                        .foregroundColor(model.isFeatureComplete ? .green : .orange)
                    Text(model.installState)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(22)
                .background(RoundedRectangle(cornerRadius: 24).fill(Color.indigo.opacity(0.12)))

                if let warning = model.warning {
                    StatusCard(
                        title: "Partial port",
                        symbol: "exclamationmark.triangle.fill",
                        color: .orange,
                        items: [warning]
                    )
                }

                StatusCard(
                    title: "Translated automatically",
                    symbol: "checkmark.seal.fill",
                    color: .green,
                    items: model.translatedCapabilities.isEmpty
                        ? ["App-container storage and the DebToIPA compatibility runtime are active."]
                        : model.translatedCapabilities
                )

                if !model.redesignItems.isEmpty {
                    StatusCard(
                        title: "Replacement implementation required",
                        symbol: "hammer.fill",
                        color: .orange,
                        items: model.redesignItems
                    )
                }

                if !model.unavailableItems.isEmpty {
                    StatusCard(
                        title: "Unavailable on stock iOS",
                        symbol: "nosign",
                        color: .red,
                        items: model.unavailableItems
                    )
                }

                VStack(alignment: .leading, spacing: 8) {
                    Label("What this IPA runs", systemImage: "shield.lefthalf.filled")
                        .font(.headline)
                    Text("This app runs DebToIPA's signed-compatible Swift host. It never executes the original jailbreak binary or hidden helper processes. Translated resources are copied into this app's own container.")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .padding(18)
                .background(RoundedRectangle(cornerRadius: 20).fill(Color.secondary.opacity(0.10)))
            }
            .padding()
        }
        .navigationTitle("Compatibility")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct FilesView: View {
    @EnvironmentObject private var model: CompatibilityHostModel

    var body: some View {
        Group {
            if model.files.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "folder.badge.questionmark")
                        .font(.system(size: 46))
                        .foregroundColor(.secondary)
                    Text("No translated files")
                        .font(.title3.bold())
                    Text("Native binaries were intentionally removed. Safe assets and configuration files appear here when available.")
                        .multilineTextAlignment(.center)
                        .foregroundColor(.secondary)
                        .padding(.horizontal)
                }
            } else {
                List(model.files) { file in
                    Button {
                        model.preview(file)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(file.relativePath)
                                .foregroundColor(.primary)
                                .lineLimit(2)
                            Text(ByteCountFormatter.string(fromByteCount: file.size, countStyle: .file))
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Translated Files")
        .sheet(item: $model.selectedFile) { file in
            NavigationView {
                ScrollView {
                    Text(model.selectedFileText)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
                .navigationTitle(file.relativePath.split(separator: "/").last.map(String.init) ?? "File")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Done") { model.selectedFile = nil }
                    }
                }
            }
        }
    }
}

private struct DiagnosticsView: View {
    @EnvironmentObject private var model: CompatibilityHostModel

    var body: some View {
        List {
            Section("Build") {
                DiagnosticRow(label: "Launchable", value: model.isLaunchable ? "Yes" : "No")
                DiagnosticRow(label: "Feature complete", value: model.isFeatureComplete ? "Yes" : "No")
                DiagnosticRow(label: "Original binary executed", value: model.manifest?.hostBuild?.originalBinaryExecuted == true ? "Yes" : "No")
                DiagnosticRow(label: "Included resources", value: String(model.manifest?.hostBuild?.includedResourceCount ?? model.files.count))
                DiagnosticRow(label: "Skipped native resources", value: String(model.manifest?.hostBuild?.skippedResourceCount ?? model.fileIndex.skipped.count))
            }

            if !model.fileIndex.skipped.isEmpty {
                Section("Removed from the IPA") {
                    ForEach(model.fileIndex.skipped.prefix(100)) { item in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.path).font(.subheadline)
                            Text(item.reason).font(.caption).foregroundColor(.secondary)
                        }
                    }
                }
            }

            if let mappings = model.manifest?.virtualPathMappings, !mappings.isEmpty {
                Section("Virtual filesystem mappings") {
                    ForEach(mappings.keys.sorted(), id: \.self) { key in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(key).font(.system(.subheadline, design: .monospaced))
                            Text(mappings[key] ?? "").font(.caption).foregroundColor(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Port Status")
    }
}

private struct StatusCard: View {
    let title: String
    let symbol: String
    let color: Color
    let items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: symbol)
                .font(.headline)
                .foregroundColor(color)
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .top, spacing: 9) {
                    Circle().fill(color.opacity(0.8)).frame(width: 6, height: 6).padding(.top, 6)
                    Text(item).font(.subheadline).foregroundColor(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 20).fill(color.opacity(0.08)))
    }
}

private struct DiagnosticRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            Text(value).foregroundColor(.secondary)
        }
    }
}
