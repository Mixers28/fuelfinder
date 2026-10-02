import CoreLocation
import SwiftUI

@main
struct FuelFinderApp: App {
    @StateObject private var preferences = UserPreferences()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(preferences)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var preferences: UserPreferences
    @StateObject private var locationManager = LocationManager()
    @State private var manualLocation: SearchLocation?
    @State private var sortOrder: SortOrder = .distance
    @State private var nearbyResponse: NearbyResponse?
    @State private var recommendation: FillNowResponse?
    @State private var isLoading = false
    @State private var isLoadingRecommendation = false
    @State private var recommendationError = false
    @State private var errorMessage: String?
    @State private var showMap = false
    @State private var showSearch = false
    @State private var showFavourites = false
    @State private var searchTask: Task<Void, Never>?

    private var searchLocation: SearchLocation? {
        if let manualLocation { return manualLocation }
        guard let coordinate = locationManager.location,
              locationManager.authorizationStatus == .authorizedWhenInUse || locationManager.authorizationStatus == .authorizedAlways else { return nil }
        return SearchLocation(name: "Near me", subtitle: "Your current location", latitude: coordinate.latitude, longitude: coordinate.longitude, isCurrentLocation: true)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if searchLocation == nil {
                    fuelPicker
                    welcomeContent
                } else {
                    sortPicker
                        .padding(.top, 8)
                    areaControls
                    fuelPicker
                    stationContent
                }
            }
            .navigationTitle("Fuel Finder")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: StationSummary.self) { station in
                StationDetailView(stationId: station.stationId, savedStation: SavedStation(station))
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button("Favourites", systemImage: "star") { showFavourites = true }
                        .accessibilityIdentifier("openFavourites")
                    if searchLocation != nil {
                        Button(showMap ? "Show list" : "Show map", systemImage: showMap ? "list.bullet" : "map") {
                            withAnimation { showMap.toggle() }
                        }
                    }
                }
            }
            .sheet(isPresented: $showSearch) {
                PlaceSearchView { manualLocation = $0 }
            }
            .sheet(isPresented: $showFavourites) {
                FavouritesView()
            }
            .onChange(of: searchLocation) { fetchStations() }
            .onChange(of: preferences.fuelType) { fetchStations() }
            .onChange(of: sortOrder) { fetchStations() }
            .task { fetchStations() }
            .onDisappear { searchTask?.cancel() }
        }
    }

    private var areaControls: some View {
        HStack {
            Button { showSearch = true } label: {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Postcode search")
                            .font(.subheadline.weight(.medium)).lineLimit(1)
                        if let location = searchLocation {
                            Text(location.isCurrentLocation ? "Currently near you" : "\(location.name), \(location.subtitle)")
                                .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.down").font(.caption)
                }
                .padding(12)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("searchArea")

            Button(action: useCurrentLocation) {
                Image(systemName: "location.fill").frame(width: 44, height: 44)
            }
            .accessibilityLabel("Use my location")
        }
        .padding(.horizontal)
        .padding(.top, 8)
    }

    private var fuelPicker: some View {
        Picker("Fuel Type", selection: $preferences.fuelType) {
            ForEach([FuelType.E10, .E5, .B7], id: \.self) { type in
                Text(type.shortName).tag(type)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var sortPicker: some View {
        Picker("Sort stations", selection: $sortOrder) {
            Text("Nearest").tag(SortOrder.distance)
            Text("Cheapest").tag(SortOrder.price)
        }
        .pickerStyle(.segmented)
        .accessibilityIdentifier("stationSort")
        .padding(.horizontal)
        .padding(.bottom, 8)
    }

    private var welcomeContent: some View {
        ScrollView {
            VStack(spacing: 16) {
                Image(systemName: "fuelpump.fill").font(.system(size: 52))
                Text("Find fuel near you").font(.title2.bold())
                Text("Find the nearest station or the cheapest fuel using your location, or search a town or postcode.")
                    .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                HStack {
                    Button {
                        sortOrder = .distance
                        useCurrentLocation()
                    } label: {
                        Label("Nearest", systemImage: "location.fill").frame(maxWidth: .infinity)
                    }
                    .accessibilityIdentifier("findNearest")
                    Button {
                        sortOrder = .price
                        useCurrentLocation()
                    } label: {
                        Label("Cheapest", systemImage: "banknote").frame(maxWidth: .infinity)
                    }
                    .accessibilityIdentifier("findCheapest")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                Button("Postcode search", systemImage: "magnifyingglass") { showSearch = true }
                    .buttonStyle(.bordered).controlSize(.large)
                    .accessibilityIdentifier("searchArea")
                if locationManager.authorizationStatus == .denied || locationManager.authorizationStatus == .restricted {
                    Text("Location is off. Enable it in Settings for nearby results, or use postcode search.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Open location settings", action: useCurrentLocation)
                } else {
                    if let error = locationManager.error {
                        Text(error).font(.caption).foregroundStyle(.secondary)
                    } else if locationManager.authorizationStatus == .authorizedWhenInUse || locationManager.authorizationStatus == .authorizedAlways {
                        ProgressView("Finding your location…")
                    }
                }
                Text("No account needed. Favourites and your fuel choice are saved on this device.")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding(28)
            .padding(.top, 24)
        }
        .frame(maxHeight: .infinity)
    }

    @ViewBuilder
    private var stationContent: some View {
        if isLoading {
            Spacer()
            ProgressView("Finding nearby prices…")
            Spacer()
        } else if let error = errorMessage {
            ContentUnavailableView {
                Label("Couldn't load prices", systemImage: "wifi.exclamationmark")
            } description: {
                Text(error)
            } actions: {
                Button("Retry") { fetchStations() }
                Button("Search another area") { showSearch = true }
            }
        } else if nearbyResponse?.stations.isEmpty == true {
            if let notice = nearbyResponse?.notice { noticeView(notice) }
            ContentUnavailableView {
                Label("No \(preferences.fuelType.shortName.lowercased()) prices nearby", systemImage: "fuelpump")
            } description: {
                Text("Try another fuel type or search a nearby town.")
            } actions: {
                Button("Search another area") { showSearch = true }
                Button("Retry") { fetchStations() }
            }
        } else if showMap, let response = nearbyResponse, let location = searchLocation {
            if let notice = response.notice { noticeView(notice) }
            StationMapView(stations: response.stations, searchLocation: location,
                           cheapestId: response.cheapest?.stationId, nearestId: response.nearest?.stationId)
                .id(location.id)
                .ignoresSafeArea(edges: .bottom)
        } else {
            listContent
        }
    }

    private func noticeView(_ notice: String) -> some View {
        Label(notice, systemImage: "info.circle")
            .font(.caption).foregroundStyle(.secondary)
            .padding(.horizontal).padding(.bottom, 8)
    }

    private var listContent: some View {
        List {
            if let notice = nearbyResponse?.notice { noticeView(notice) }
            if sortOrder == .price {
                if let recommendation {
                    SavingsCard(response: recommendation)
                        .listRowSeparator(.hidden)
                } else if isLoadingRecommendation {
                    ProgressView("Comparing fuel savings…").font(.caption)
                } else if recommendationError {
                    Text("Savings estimate unavailable. You can still compare prices below.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if let response = nearbyResponse {
                Text("\(response.stations.count) of \(response.total) stations")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Distances and savings are from \(searchLocation?.name ?? "the search area").")
                    .font(.caption2).foregroundStyle(.secondary)
                    .listRowSeparator(.hidden)
                ForEach(response.stations) { station in
                    NavigationLink(value: station) {
                        StationRow(station: station,
                                   isCheapest: station.id == response.cheapest?.id,
                                   isNearest: station.id == response.nearest?.id,
                                   cheapestPrice: response.cheapest?.price?.pencePerLitre)
                    }
                    .swipeActions(edge: .trailing) {
                        FavouriteButton(station: SavedStation(station)).tint(.orange)
                    }
                }
            }
        }
        .listStyle(.plain)
    }

    private func useCurrentLocation() {
        switch locationManager.authorizationStatus {
        case .denied, .restricted:
            if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
        case .notDetermined:
            manualLocation = nil
            locationManager.requestPermission()
        default:
            manualLocation = nil
            locationManager.requestLocation()
        }
    }

    private func fetchStations() {
        searchTask?.cancel()
        nearbyResponse = nil
        recommendation = nil
        errorMessage = nil
        recommendationError = false
        isLoadingRecommendation = false
        guard let location = searchLocation else { isLoading = false; return }
        let fuelType = preferences.fuelType
        let sort = sortOrder
        isLoading = true
        searchTask = Task {
            do {
                let response = try await FuelFinderAPI.shared.nearbyStations(
                    lat: location.latitude, lng: location.longitude, fuelType: fuelType, sort: sort
                )
                try Task.checkCancellation()
                nearbyResponse = response
                isLoading = false
                guard !response.stations.isEmpty, sort == .price else { return }
                isLoadingRecommendation = true
                do {
                    let result = try await FuelFinderAPI.shared.fillNow(
                        lat: location.latitude, lng: location.longitude, fuelType: fuelType,
                        radius: response.radiusMiles
                    )
                    try Task.checkCancellation()
                    recommendation = result
                } catch {
                    guard !Task.isCancelled else { return }
                    recommendationError = true
                }
                isLoadingRecommendation = false
            } catch {
                guard !Task.isCancelled else { return }
                errorMessage = error.localizedDescription
                isLoading = false
            }
        }
    }
}

// MARK: - Station Row

struct StationRow: View {
    let station: StationSummary
    let isCheapest: Bool
    let isNearest: Bool
    let cheapestPrice: Double?
    
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(station.tradingName)
                        .font(.subheadline.bold())
                    Text(station.postcode)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                
                Spacer()
                
                if let price = station.price {
                    Text(price.formattedPrice)
                        .font(.title3.bold().monospacedDigit())
                        .foregroundStyle(isCheapest ? .green : .primary)
                }
            }
            
            HStack(spacing: 12) {
                Label(station.formattedDistance, systemImage: "location")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                
                if let price = station.price {
                    Label(price.timeAgo, systemImage: "clock")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                
                Spacer()
                
                if isCheapest {
                    Text("Cheapest")
                        .font(.caption2.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(.green.opacity(0.15))
                        .foregroundStyle(.green)
                        .clipShape(Capsule())
                } else if isNearest {
                    Text("Nearest")
                        .font(.caption2.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(.blue.opacity(0.15))
                        .foregroundStyle(.blue)
                        .clipShape(Capsule())
                } else if let cheapest = cheapestPrice, let price = station.price {
                    let diff = price.pencePerLitre - cheapest
                    if diff > 0 {
                        Text("+\(String(format: "%.1f", diff))\(price.currency == "EUR" ? "c" : "p")/L")
                            .font(.caption2.bold())
                            .foregroundStyle(.red)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }
}
