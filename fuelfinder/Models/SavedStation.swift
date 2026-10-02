import Foundation

/// Only station metadata is saved. Prices and distances must be fetched again.
struct SavedStation: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let address: String
    let postcode: String
    let latitude: Double
    let longitude: Double

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
