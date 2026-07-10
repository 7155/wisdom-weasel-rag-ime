import Foundation

struct SettingsSchemaClient {
    let api: ManagementAPIClient

    func load() async throws -> (SettingsSchemaResponse, SettingsResponse) {
        async let schema: SettingsSchemaResponse = api.get("api/settings/schema")
        async let settings: SettingsResponse = api.get("api/settings")
        return try await (schema, settings)
    }

    func update(key: String, value: JSONValue) async throws -> MutationResponse {
        try await api.post("api/settings/update", body: [key: value, "updatedBy": .string("native-control-center")])
    }
}
