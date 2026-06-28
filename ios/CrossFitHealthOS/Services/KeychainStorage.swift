import Foundation
import Security

enum KeychainStorage {
    private static let service = "com.crossfithealthos.tokens"

    static var accessToken: String? {
        get { read(key: "access_token") }
        set {
            if let newValue { save(key: "access_token", value: newValue) }
            else { delete(key: "access_token") }
        }
    }

    static var refreshToken: String? {
        get { read(key: "refresh_token") }
        set {
            if let newValue { save(key: "refresh_token", value: newValue) }
            else { delete(key: "refresh_token") }
        }
    }

    static func clearTokens() {
        accessToken = nil
        refreshToken = nil
    }

    private static func save(key: String, value: String) {
        delete(key: key)
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func read(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else { return nil }
        return value
    }

    private static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
