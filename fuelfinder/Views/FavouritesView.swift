import MapKit
import SwiftUI

struct FavouritesView: View {
    @EnvironmentObject private var preferences: UserPreferences
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if preferences.favourites.isEmpty {
                    ContentUnavailableView("No favourites yet", systemImage: "star", description: Text("Save a station with the star button to find it here later."))
                } else {
                    List {
                        Section {
                            ForEach(preferences.favourites) { station in
                                SavedStationRow(station: station)
                                .swipeActions {
                                    Button("Remove", role: .destructive) { preferences.remove(station.id) }
                                }
                            }
                        } footer: {
                            Text("Saved on this device. Open a station to check its latest available prices.")
                        }
                    }
                }
            }
            .navigationTitle("Favourites")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

private struct SavedStationRow: View {
    let station: SavedStation
    @State private var resolved: SavedStation?
    @State private var failed = false

    var body: some View {
        let displayed = resolved ?? station
        NavigationLink {
            StationDetailView(stationId: station.id, savedStation: displayed)
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(displayed.name).font(.headline)
                if displayed.hasDetails {
                    Text("\(displayed.address) \(displayed.postcode)")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text(failed ? "Details unavailable. Open to retry." : "Loading station details…")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .task(id: station.id) {
            guard station.isPetromap else { return }
            do {
                let detail = try await FuelFinderAPI.shared.stationDetail(stationId: station.id)
                try Task.checkCancellation()
                resolved = SavedStation(detail)
            } catch {
                guard !Task.isCancelled else { return }
                failed = true
            }
        }
    }
}

struct FavouriteButton: View {
    let station: SavedStation
    @EnvironmentObject private var preferences: UserPreferences

    var body: some View {
        Button {
            preferences.toggle(station)
        } label: {
            Label(preferences.contains(station.id) ? "Remove from favourites" : "Save to favourites",
                  systemImage: preferences.contains(station.id) ? "star.fill" : "star")
        }
        .accessibilityIdentifier("favouriteStation")
    }
}

struct DirectionsButton: View {
    let station: SavedStation
    @State private var showError = false

    var body: some View {
        Button("Directions", systemImage: "arrow.triangle.turn.up.right.diamond.fill") {
            guard let latitude = station.latitude, let longitude = station.longitude else { return }
            let item = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(
                latitude: latitude, longitude: longitude
            )))
            item.name = station.name
            showError = !item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving])
        }
        .disabled(!station.hasDetails)
        .accessibilityHint("Opens driving directions in Apple Maps from your current location")
        .alert("Couldn't open Apple Maps", isPresented: $showError) {
            Button("OK", role: .cancel) { }
        } message: {
            Text("Check that Apple Maps is installed, then try again.")
        }
    }
}
