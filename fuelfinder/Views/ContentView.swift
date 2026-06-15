import CoreLocation
import SwiftUI

@main
struct FuelFinderApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    @StateObject private var locationManager = LocationManager()
    @State private var selectedFuelType: FuelType = .E10
    @State private var sortOrder: SortOrder = .price
    @State private var nearbyResponse: NearbyResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var selectedStation: StationSummary?
    @State private var showMap = false
    
    var body: some View {
        NavigationStack {
            Group {
                switch locationManager.authorizationStatus {
                case .notDetermined:
                    locationPermissionView
                case .denied, .restricted:
                    locationDeniedView
                default:
                    if locationManager.hasLocation {
                        stationListView
                    } else {
                        ProgressView("Finding your location…")
                    }
                }
            }
            .navigationTitle("Fuel Finder")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
    
    // MARK: - Permission Screen
    
    private var locationPermissionView: some View {
        VStack(spacing: 24) {
            Image(systemName: "fuelpump.fill")
                .font(.system(size: 56))
                .foregroundStyle(.primary)
            
            Text("Find Cheap Fuel Nearby")
                .font(.title2.bold())
            
            Text("Your location is used only to find nearby stations. It is not stored, tracked, or shared.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            
            Button("Find stations near me") {
                locationManager.requestPermission()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            
            Text("Prices from the GOV.UK Fuel Finder scheme")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }
    
    private var locationDeniedView: some View {
        VStack(spacing: 16) {
            Image(systemName: "location.slash")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            
            Text("Location Access Required")
                .font(.title3.bold())
            
            Text("Open Settings → Privacy → Location Services to allow access while using the app.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
    }
    
    // MARK: - Station List / Map

    private var stationListView: some View {
        VStack(spacing: 0) {
            Picker("Fuel Type", selection: $selectedFuelType) {
                ForEach([FuelType.E10, .E5, .B7], id: \.self) { type in
                    Text(type.shortName).tag(type)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            .padding(.vertical, 8)
            .onChange(of: selectedFuelType) { fetchStations() }

            if showMap {
                mapContent
            } else {
                listContent
            }
        }
        .navigationDestination(for: StationSummary.self) { station in
            StationDetailView(stationId: station.stationId, fuelType: selectedFuelType)
        }
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button {
                    withAnimation { showMap.toggle() }
                } label: {
                    Image(systemName: showMap ? "list.bullet" : "map")
                }
            }
        }
        .task { fetchStations() }
    }

    @ViewBuilder
    private var mapContent: some View {
        if let response = nearbyResponse, let coord = locationManager.location {
            StationMapView(
                stations: response.stations,
                userCoordinate: coord,
                cheapestId: response.cheapest?.stationId,
                nearestId: response.nearest?.stationId,
                selectedFuelType: selectedFuelType
            )
            .ignoresSafeArea(edges: .bottom)
        } else if isLoading {
            Spacer()
            ProgressView()
            Spacer()
        }
    }

    @ViewBuilder
    private var listContent: some View {
        HStack {
            if let response = nearbyResponse {
                Text("\(response.total) stations")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Picker("Sort", selection: $sortOrder) {
                Text("Cheapest").tag(SortOrder.price)
                Text("Nearest").tag(SortOrder.distance)
            }
            .pickerStyle(.segmented)
            .frame(width: 200)
            .onChange(of: sortOrder) { fetchStations() }
        }
        .padding(.horizontal)
        .padding(.bottom, 8)

        if isLoading {
            Spacer()
            ProgressView()
            Spacer()
        } else if let error = errorMessage {
            Spacer()
            Text(error).foregroundStyle(.secondary).padding()
            Button("Retry") { fetchStations() }
            Spacer()
        } else {
            List {
                if let stations = nearbyResponse?.stations {
                    ForEach(stations) { station in
                        NavigationLink(value: station) {
                            StationRow(
                                station: station,
                                isCheapest: station.stationId == nearbyResponse?.cheapest?.stationId,
                                isNearest: station.stationId == nearbyResponse?.nearest?.stationId,
                                cheapestPrice: nearbyResponse?.cheapest?.price?.pencePerLitre
                            )
                        }
                    }
                }
            }
            .listStyle(.plain)
        }
    }
    
    // MARK: - Data Fetching
    
    private func fetchStations() {
        guard let coord = locationManager.location else { return }
        isLoading = true
        errorMessage = nil
        
        Task {
            do {
                nearbyResponse = try await FuelFinderAPI.shared.nearbyStations(
                    lat: coord.latitude,
                    lng: coord.longitude,
                    fuelType: selectedFuelType,
                    sort: sortOrder
                )
                isLoading = false
            } catch {
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
                        Text("+\(String(format: "%.1f", diff))p")
                            .font(.caption2.bold())
                            .foregroundStyle(.red)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }
}
