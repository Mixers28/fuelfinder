import Foundation

/// Prices and distances are never saved. Petromap favourites retain only an ID;
/// their licensed station metadata is loaded when the favourite is displayed.
struct SavedStation: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let address: String
    let postcode: String
    let latitude: Double?
    let longitude: Double?

    var isPetromap: Bool { id.hasPrefix("nl_pm_") }
    var hasDetails: Bool { latitude != nil && longitude != nil }

    init(referenceID: String) {
        id = referenceID
        name = "Saved Dutch station"
        address = ""
        postcode = ""
        latitude = nil
        longitude = nil
    }

    private enum CodingKeys: String, CodingKey {
        case id, name, address, postcode, latitude, longitude
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        if id.hasPrefix("nl_pm_") {
            name = "Saved Dutch station"
            address = ""
            postcode = ""
            latitude = nil
            longitude = nil
        } else {
            name = try container.decode(String.self, forKey: .name)
            address = try container.decode(String.self, forKey: .address)
            postcode = try container.decode(String.self, forKey: .postcode)
            latitude = try container.decode(Double.self, forKey: .latitude)
            longitude = try container.decode(Double.self, forKey: .longitude)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        guard !isPetromap else { return }
        try container.encode(name, forKey: .name)
        try container.encode(address, forKey: .address)
        try container.encode(postcode, forKey: .postcode)
        try container.encodeIfPresent(latitude, forKey: .latitude)
        try container.encodeIfPresent(longitude, forKey: .longitude)
    }

    init(_ station: StationSummary) {
        id = station.stationId
        name = station.tradingName
        address = station.address
        postcode = station.postcode
        latitude = station.latitude
        longitude = station.longitude
    }

    init(_ station: StationDetail) {
        id = station.stationId
        name = station.tradingName
        address = station.address
        postcode = station.postcode
        latitude = station.latitude
        longitude = station.longitude
    }
}

struct SearchLocation: Equatable, Identifiable {
    let name: String
    let subtitle: String
    let latitude: Double
    let longitude: Double
    var isCurrentLocation = false

    var id: String { "\(latitude),\(longitude)" }
}
