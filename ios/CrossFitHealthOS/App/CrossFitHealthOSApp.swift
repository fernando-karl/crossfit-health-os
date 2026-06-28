import SwiftUI

@main
struct CrossFitHealthOSApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
        }
    }
}

final class AppState: ObservableObject {
    @Published var isAuthenticated: Bool = KeychainStorage.accessToken != nil
    @Published var lastSyncMessage: String?
    @Published var isSyncing: Bool = false

    let api = APIClient()
    let healthKit = HealthKitManager()
}
