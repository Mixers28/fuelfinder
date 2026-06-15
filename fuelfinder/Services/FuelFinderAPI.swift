import Foundation

// MARK: - API Client

class FuelFinderAPI {
    static let shared = FuelFinderAPI()
    
    // Point this at your deployed backend
    private let baseURL = "https://fuelfinder-production.up.railway.app"
    
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
    
    // MARK: - Nearby Stations
    
    func nearbyStations(
        lat: Double,
        lng: Double,
        fuelType: FuelType = .E10,
        sort: SortOrder = .price,
        radius: Double = 15.0,
        limit: Int = 20
    ) async throws -> NearbyResponse {
        var components = URLComponents(string: "\(baseURL)/stations/nearby")!
        components.queryItems = [
            URLQueryItem(name: "lat", value: "\(lat)"),
            URLQueryItem(name: "lng", value: "\(lng)"),
            URLQueryItem(name: "fuel_type", value: fuelType.rawValue),
            URLQueryItem(name: "sort", value: sort.rawValue),
            URLQueryItem(name: "radius", value: "\(radius)"),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]
        
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw APIError.badResponse
        }
        return try decoder.decode(NearbyResponse.self, from: data)
    }
    
    // MARK: - Station Detail
    
    func stationDetail(stationId: String) async throws -> StationDetail {
        let url = URL(string: "\(baseURL)/stations/\(stationId)")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw APIError.badResponse
        }
        return try decoder.decode(StationDetail.self, from: data)
    }
    
    // MARK: - Fill Now Recommendation
    
    func fillNow(
        lat: Double,
        lng: Double,
        fuelType: FuelType = .E10,
        radius: Double = 15.0,
        tankLitres: Double = 40.0
    ) async throws -> FillNowResponse {
        var components = URLComponents(string: "\(baseURL)/recommendation/fill-now")!
        components.queryItems = [
            URLQueryItem(name: "lat", value: "\(lat)"),
            URLQueryItem(name: "lng", value: "\(lng)"),
            URLQueryItem(name: "fuel_type", value: fuelType.rawValue),
            URLQueryItem(name: "radius", value: "\(radius)"),
            URLQueryItem(name: "tank_litres", value: "\(tankLitres)"),
        ]
        
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw APIError.badResponse
        }
        return try decoder.decode(FillNowResponse.self, from: data)
    }
}

enum APIError: LocalizedError {
    case badResponse
    case decodingFailed
    
    var errorDescription: String? {
        switch self {
        case .badResponse: return "Server returned an error"
        case .decodingFailed: return "Failed to parse response"
        }
    }
}
