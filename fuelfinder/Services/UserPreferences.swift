import Combine
import Foundation

@MainActor
final class UserPreferences: ObservableObject {
    private let defaults: UserDefaults
    private static let fuelKey = "selectedFuelType"
    private static let favouritesKey = "favouriteStations"

    @Published var fuelType: FuelType {
        didSet { defaults.set(fuelType.rawValue, forKey: Self.fuelKey) }
    }
    @Published private(set) var favourites: [SavedStation]

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        fuelType = FuelType(rawValue: defaults.string(forKey: Self.fuelKey) ?? "") ?? .E10
        if let data = defaults.data(forKey: Self.favouritesKey),
           let saved = try? JSONDecoder().decode([SavedStation].self, from: data) {
            var seen = Set<String>()
            favourites = saved.filter { seen.insert($0.id).inserted }
        } else {
            favourites = []
        }
    }

    func contains(_ stationID: String) -> Bool {
        favourites.contains { $0.id == stationID }
    }

    func toggle(_ station: SavedStation) {
        if contains(station.id) {
            remove(station.id)
        } else {
            favourites.append(station.isPetromap ? SavedStation(referenceID: station.id) : station)
            persistFavourites()
        }
    }

    func remove(_ stationID: String) {
        favourites.removeAll { $0.id == stationID }
        persistFavourites()
    }

    private func persistFavourites() {
        if let data = try? JSONEncoder().encode(favourites) {
            defaults.set(data, forKey: Self.favouritesKey)
        }
    }
}
