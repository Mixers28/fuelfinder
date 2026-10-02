import XCTest
@testable import fuelfinder

private final class StubProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    override func stopLoading() { }
}

final class FuelFinderAPITests: XCTestCase {
    @MainActor
    func testSavingsAgeWarningIncludesBothComparedPrices() async throws {
        func station(_ id: String, age: TimeInterval) -> StationSummary {
            StationSummary(stationId: id, tradingName: id, brand: nil, address: "Road", postcode: "ABC",
                           latitude: 1, longitude: 2, distanceMiles: 1,
                           price: FuelPrice(fuelType: .E10, pencePerLitre: 150, updatedAt: Date().addingTimeInterval(-age), currency: "GBP"),
                           country: "uk")
        }
        let recommendation = WorthItRecommendation(recommendedStationId: "cheap", recommendedStationName: "cheap", netSavingPence: 100,
                                                   extraMilesRoundTrip: 1, savingPerLitrePence: 3, worthDriving: true, explanation: "Estimate")
        let oldBaseline = FillNowResponse(fuelType: .E10, cheapest: station("cheap", age: 60), nearest: station("near", age: 172800),
                                         recommendation: recommendation, notice: nil)
        XCTAssertTrue(oldBaseline.hasOlderPriceReports)
        XCTAssertGreaterThan(Date().timeIntervalSince(try XCTUnwrap(oldBaseline.oldestComparedPrice).updatedAt), 86400)
        let fresh = FillNowResponse(fuelType: .E10, cheapest: station("cheap", age: 60), nearest: station("near", age: 3600),
                                   recommendation: recommendation, notice: nil)
        XCTAssertFalse(fresh.hasOlderPriceReports)
    }

    @MainActor
    private func client() -> FuelFinderAPI {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        return FuelFinderAPI(baseURL: "https://example.invalid/", session: URLSession(configuration: configuration))
    }

    @MainActor
    func testManualSearchCoordinatesAndOfficialFuelCodeReachAPI() async throws {
        StubProtocol.handler = { request in
            let url = try XCTUnwrap(request.url)
            XCTAssertEqual(url.path, "/stations/nearby")
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)!.queryItems!
            let values = Dictionary(uniqueKeysWithValues: query.map { ($0.name, $0.value ?? "") })
            XCTAssertEqual(values["lat"], "52.37")
            XCTAssertEqual(values["lng"], "9.73")
            XCTAssertEqual(values["fuel_type"], "B7")
            XCTAssertEqual(values["sort"], "distance")
            return (200, Data(#"{"stations":[],"cheapest":null,"nearest":null,"total":0,"fuel_type":"B7","user_lat":52.37,"user_lng":9.73,"radius_miles":15}"#.utf8))
        }
        defer { StubProtocol.handler = nil }
        let response = try await client().nearbyStations(lat: 52.37, lng: 9.73, fuelType: .B7, sort: .distance)
        XCTAssertNil(response.notice) // Compatible with an older deployed backend.
        XCTAssertEqual(response.fuelType, .B7)
    }

    @MainActor
    func testSavingsRequestUsesSelectedAreaFuelAndFillSizeAndPropagatesOutage() async throws {
        StubProtocol.handler = { request in
            let url = try XCTUnwrap(request.url)
            XCTAssertEqual(url.path, "/recommendation/fill-now")
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)!.queryItems!
            let values = Dictionary(uniqueKeysWithValues: query.map { ($0.name, $0.value ?? "") })
            XCTAssertEqual(values["lat"], "52.37")
            XCTAssertEqual(values["lng"], "9.73")
            XCTAssertEqual(values["fuel_type"], "E5")
            XCTAssertEqual(values["tank_litres"], "40.0")
            XCTAssertEqual(values["radius"], "14.0")
            return (503, Data(#"{"detail":"German prices are temporarily unavailable."}"#.utf8))
        }
        defer { StubProtocol.handler = nil }
        do {
            _ = try await client().fillNow(lat: 52.37, lng: 9.73, fuelType: .E5, radius: 14)
            XCTFail("An unavailable estimate must not appear as a successful recommendation")
        } catch {
            XCTAssertEqual(error.localizedDescription, "German prices are temporarily unavailable.")
        }
    }
}
