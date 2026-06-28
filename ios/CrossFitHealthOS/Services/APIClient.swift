import Foundation

struct HealthKitSyncResponse: Decodable {
    let status: String
    let recordsSynced: Int?
    let recoveryMetricUpdated: Bool?
    let metricDate: String?
    let readinessScore: Int?

    enum CodingKeys: String, CodingKey {
        case status
        case recordsSynced = "records_synced"
        case recoveryMetricUpdated = "recovery_metric_updated"
        case metricDate = "metric_date"
        case readinessScore = "readiness_score"
    }
}

enum APIError: LocalizedError {
    case invalidURL
    case unauthorized
    case server(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "URL da API inválida"
        case .unauthorized: return "Sessão expirada — faça login novamente"
        case .server(let code, let msg): return "HTTP \(code): \(msg)"
        }
    }
}

final class APIClient {
    var baseURL: String = ""

    private var apiRoot: URL? {
        guard !baseURL.isEmpty, let url = URL(string: baseURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return nil
        }
        return url
    }

    func login(email: String, password: String) async throws {
        guard let root = apiRoot else { throw APIError.invalidURL }
        var request = URLRequest(url: root.appendingPathComponent("/api/v1/auth/login"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["email": email, "password": password])

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)

        struct LoginResponse: Decodable {
            let accessToken: String
            let refreshToken: String?

            enum CodingKeys: String, CodingKey {
                case accessToken = "access_token"
                case refreshToken = "refresh_token"
            }
        }

        let decoded = try JSONDecoder().decode(LoginResponse.self, from: data)
        KeychainStorage.accessToken = decoded.accessToken
        KeychainStorage.refreshToken = decoded.refreshToken
    }

    func syncHealthKit(payload: [String: Any]) async throws -> HealthKitSyncResponse {
        guard let root = apiRoot else { throw APIError.invalidURL }
        guard let token = KeychainStorage.accessToken else { throw APIError.unauthorized }

        var request = URLRequest(url: root.appendingPathComponent("/api/v1/integrations/healthkit/sync"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, response) = try await URLSession.shared.data(for: request)
        if (response as? HTTPURLResponse)?.statusCode == 401 {
            KeychainStorage.clearTokens()
            throw APIError.unauthorized
        }
        try validate(response: response, data: data)
        return try JSONDecoder().decode(HealthKitSyncResponse.self, from: data)
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw APIError.server(http.statusCode, body)
        }
    }
}
