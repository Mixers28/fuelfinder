import XCTest
@testable import fuelfinder

final class UserPreferencesTests: XCTestCase {
    @MainActor
    func testFuelAndFavouritesSurviveRelaunchAndRemoval() async throws {
        let suite = "FuelFinderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let preferences = UserPreferences(defaults: defaults)
        preferences.fuelType = .B7
        let station = StationSummary(stationId: "de_test", tradingName: "Test Station", brand: nil,
                                     address: "Test Street", postcode: "30159", latitude: 52.37, longitude: 9.73,
                                     distanceMiles: 2, price: FuelPrice(fuelType: .B7, pencePerLitre: 169.9,
                                                                      updatedAt: Date(), currency: "EUR"), country: "de")
        preferences.toggle(SavedStation(station))

        let reloaded = UserPreferences(defaults: defaults)
        XCTAssertEqual(reloaded.fuelType, .B7)
        XCTAssertEqual(reloaded.favourites.map(\.id), ["de_test"])
        XCTAssertEqual(reloaded.favourites.first?.postcode, "30159")
        // Saved metadata must not make old prices or old user distances appear current.
        let savedData = try XCTUnwrap(defaults.data(forKey: "favouriteStations"))
        let savedJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: savedData) as? [[String: Any]])
        XCTAssertNil(savedJSON.first?["price"])
        XCTAssertNil(savedJSON.first?["distanceMiles"])

        reloaded.toggle(SavedStation(station))
        XCTAssertTrue(UserPreferences(defaults: defaults).favourites.isEmpty)
        XCTAssertEqual(UserPreferences(defaults: defaults).fuelType, .B7)
    }

    @MainActor
    func testInvalidPreferencesRecoverToUsableDefaults() async throws {
        let suite = "FuelFinderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("unknown-fuel", forKey: "selectedFuelType")
        defaults.set(Data("broken JSON".utf8), forKey: "favouriteStations")
        let preferences = UserPreferences(defaults: defaults)
        XCTAssertEqual(preferences.fuelType, .E10)
        XCTAssertTrue(preferences.favourites.isEmpty)
    }

    @MainActor
    func testDuplicateSavedIDsAreCollapsed() async throws {
        let suite = "FuelFinderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let station = SavedStation(StationDetail(stationId: "test", tradingName: "Station", brand: nil,
                                                address: "Road", postcode: "ABC", latitude: 1, longitude: 2,
                                                amenities: [], openingHours: nil, prices: [], country: "uk"))
        defaults.set(try JSONEncoder().encode([station, station]), forKey: "favouriteStations")
        let preferences = UserPreferences(defaults: defaults)
        XCTAssertEqual(preferences.favourites.count, 1)
        preferences.remove("test")
        XCTAssertTrue(UserPreferences(defaults: defaults).favourites.isEmpty)
    }
}
