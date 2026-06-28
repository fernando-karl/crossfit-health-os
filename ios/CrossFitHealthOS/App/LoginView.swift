import SwiftUI

struct LoginView: View {
    @EnvironmentObject var appState: AppState
    @Binding var apiBaseURL: String

    @State private var email = ""
    @State private var password = ""
    @State private var errorMessage: String?
    @State private var isLoading = false

    var body: some View {
        Form {
            Section("Servidor") {
                TextField("URL da API", text: $apiBaseURL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
            }

            Section("Conta") {
                TextField("E-mail", text: $email)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.emailAddress)
                SecureField("Senha", text: $password)
            }

            if let errorMessage {
                Section {
                    Text(errorMessage).foregroundStyle(.red).font(.footnote)
                }
            }

            Section {
                Button {
                    Task { await login() }
                } label: {
                    HStack {
                        if isLoading { ProgressView() }
                        Text("Entrar")
                    }
                }
                .disabled(isLoading || email.isEmpty || password.isEmpty)
            }
        }
    }

    private func login() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        appState.api.baseURL = apiBaseURL
        do {
            try await appState.api.login(email: email, password: password)
            appState.isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
