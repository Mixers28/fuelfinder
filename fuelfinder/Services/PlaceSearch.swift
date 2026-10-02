import Combine
import MapKit

enum SearchCountry: String, CaseIterable, Identifiable {
    case uk = "GB", germany = "DE", netherlands = "NL"

    var id: String { rawValue }
    var name: String {
        switch self {
        case .uk: return "United Kingdom"
        case .germany: return "Germany"
        case .netherlands: return "Netherlands"
        }
    }

    var region: MKCoordinateRegion {
        switch self {
        case .uk:
            return MKCoordinateRegion(center: .init(latitude: 54.5, longitude: -3), span: .init(latitudeDelta: 12, longitudeDelta: 12))
        case .germany:
            return MKCoordinateRegion(center: .init(latitude: 51.1, longitude: 10.4), span: .init(latitudeDelta: 8, longitudeDelta: 10))
        case .netherlands:
            return MKCoordinateRegion(center: .init(latitude: 52.2, longitude: 5.3), span: .init(latitudeDelta: 4, longitudeDelta: 5))
        }
    }
}

@MainActor
final class PlaceSearch: ObservableObject {
    @Published private(set) var results: [SearchLocation] = []
    @Published private(set) var isSearching = false
    @Published private(set) var message: String?

    private var search: MKLocalSearch?
    private var task: Task<Void, Never>?

    func cancel() {
        task?.cancel()
        search?.cancel()
        task = nil
        search = nil
        isSearching = false
        results = []
        message = nil
    }

    func find(_ query: String, country: SearchCountry) {
        cancel()
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }

        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = "\(query), \(country.name)"
        request.resultTypes = .address
        request.region = country.region
        let search = MKLocalSearch(request: request)
        self.search = search
        isSearching = true

        task = Task {
            do {
                let response = try await search.start()
                try Task.checkCancellation()
                var seen = Set<String>()
                results = response.mapItems.compactMap { item in
                    let place = item.placemark
                    guard place.isoCountryCode == country.rawValue else { return nil }
                    let location = SearchLocation(
                        name: item.name ?? place.locality ?? query,
                        subtitle: [place.postalCode, place.locality, place.country]
                            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", "),
                        latitude: place.coordinate.latitude,
                        longitude: place.coordinate.longitude
                    )
                    return seen.insert(location.id).inserted ? location : nil
                }
                if results.isEmpty {
                    message = "No places found in \(country.name). Check the country or try a nearby town."
                }
            } catch {
                guard !Task.isCancelled else { return }
                message = "Couldn't search places. Check your connection and try again."
            }
            guard !Task.isCancelled else { return }
            isSearching = false
            self.search = nil
        }
    }
}
