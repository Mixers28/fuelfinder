import Foundation

// MARK: - Fuel Types

enum FuelType: String, Codable, CaseIterable, Identifiable {
    case E10, E5, B7, SDV
    
    var id: String { rawValue }
    
    var displayName: String {
        switch self {
        case .E10: return "Unleaded (E10)"
        case .E5: return "Super (E5)"
        case .B7: return "Diesel (B7)"
        case .SDV: return "Premium Diesel"
        }
    }
    
    var shortName: String { rawValue }
}

enum SortOrder: String {
    case price, distance
}

// MARK: - API Response Models

struct FuelPrice: Codable, Identifiable, Hashable {
    let fuelType: FuelType
    let pencePerLitre: Double
    let updatedAt: Date
    
    var id: String { fuelType.rawValue }
    
    var formattedPrice: String {
        String(format: "£%.3f", pencePerLitre / 100.0)
    }
    
    var timeAgo: String {
        let interval = Date().timeIntervalSince(updatedAt)
        let minutes = Int(interval / 60)
        if minutes < 1 { return "just now" }
        if minutes < 60 { return "\(minutes)m ago" }
        let hours = minutes / 60
        if hours < 24 { return "\(hours)h \(minutes % 60)m ago" }
        return "\(hours / 24)d ago"
    }
    
    enum CodingKeys: String, CodingKey {
        case fuelType = "fuel_type"
        case pencePerLitre = "pence_per_litre"
        case updatedAt = "updated_at"
    }
}

struct StationSummary: Codable, Identifiable, Hashable {
    let stationId: String
    let tradingName: String
    let brand: String?
    let address: String
    let postcode: String
    let latitude: Double
    let longitude: Double
    let distanceMiles: Double
    let price: FuelPrice?
    
    var id: String { stationId }
    
    var formattedDistance: String {
        String(format: "%.1f mi", distanceMiles)
    }
    
    enum CodingKeys: String, CodingKey {
        case stationId = "station_id"
        case tradingName = "trading_name"
        case brand, address, postcode, latitude, longitude
        case distanceMiles = "distance_miles"
        case price
    }
}

struct StationDetail: Codable, Identifiable {
    let stationId: String
    let tradingName: String
    let brand: String?
    let address: String
    let postcode: String
    let latitude: Double
    let longitude: Double
    let amenities: [String]
    let openingHours: String?
    let prices: [FuelPrice]
    
    var id: String { stationId }
    
    enum CodingKeys: String, CodingKey {
        case stationId = "station_id"
        case tradingName = "trading_name"
        case brand, address, postcode, latitude, longitude, amenities
        case openingHours = "opening_hours"
        case prices
    }
}

struct WorthItRecommendation: Codable {
    let recommendedStationId: String
    let recommendedStationName: String
    let netSavingPence: Int
    let extraMilesRoundTrip: Double
    let savingPerLitrePence: Double
    let worthDriving: Bool
    let explanation: String
    
    enum CodingKeys: String, CodingKey {
        case recommendedStationId = "recommended_station_id"
        case recommendedStationName = "recommended_station_name"
        case netSavingPence = "net_saving_pence"
        case extraMilesRoundTrip = "extra_miles_round_trip"
        case savingPerLitrePence = "saving_per_litre_pence"
        case worthDriving = "worth_driving"
        case explanation
    }
}

struct NearbyResponse: Codable {
    let stations: [StationSummary]
    let cheapest: StationSummary?
    let nearest: StationSummary?
    let total: Int
    let fuelType: FuelType
    let userLat: Double
    let userLng: Double
    let radiusMiles: Double
    
    enum CodingKeys: String, CodingKey {
        case stations, cheapest, nearest, total
        case fuelType = "fuel_type"
        case userLat = "user_lat"
        case userLng = "user_lng"
        case radiusMiles = "radius_miles"
    }
}

struct FillNowResponse: Codable {
    let fuelType: FuelType
    let cheapest: StationSummary
    let nearest: StationSummary
    let recommendation: WorthItRecommendation
    
    enum CodingKeys: String, CodingKey {
        case fuelType = "fuel_type"
        case cheapest, nearest, recommendation
    }
}
