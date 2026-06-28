import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @AppStorage("apiBaseURL") private var apiBaseURL: String = "https://crossfit.example.com"

    var body: some View {
        NavigationStack {
            Group {
                if appState.isAuthenticated {
                    syncDashboard
                } else {
                    LoginView(apiBaseURL: $apiBaseURL)
                }
            }
            .navigationTitle("CHOS Health")
        }
        .onAppear {
            appState.api.baseURL = apiBaseURL
        }
        .onChange(of: apiBaseURL) { _, newValue in
            appState.api.baseURL = newValue
        }
    }

    private var syncDashboard: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Sincronize HRV, sono e FC de repouso com o CrossFit Health OS.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if let msg = appState.lastSyncMessage {
                Text(msg)
                    .font(.footnote)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            Button {
                Task { await requestHealthAndSync() }
            } label: {
                HStack {
                    if appState.isSyncing {
                        ProgressView().tint(.white)
                    }
                    Text(appState.isSyncing ? "Sincronizando…" : "Sincronizar agora")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(appState.isSyncing)

            Button("Sair", role: .destructive) {
                KeychainStorage.clearTokens()
                appState.isAuthenticated = false
            }

            Spacer()
        }
        .padding()
        .task {
            await requestHealthAndSync()
        }
    }

    private func requestHealthAndSync() async {
        appState.isSyncing = true
        defer { appState.isSyncing = false }

        do {
            try await appState.healthKit.requestAuthorization()
            let payload = try await appState.healthKit.buildDailyPayload()
            let response = try await appState.api.syncHealthKit(payload: payload)
            appState.lastSyncMessage = "OK — readiness \(response.readinessScore.map(String.init) ?? "—"), data \(response.metricDate ?? "—")"
        } catch {
            appState.lastSyncMessage = "Erro: \(error.localizedDescription)"
        }
    }
}
