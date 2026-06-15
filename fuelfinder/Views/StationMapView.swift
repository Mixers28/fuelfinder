import MapKit
import SwiftUI

struct StationMapView: View {
    let stations: [StationSummary]
    let userCoordinate: CLLocationCoordinate2D
    let cheapestId: String?
    let nearestId: String?
    let selectedFuelType: FuelType

    @State private var selectedStation: StationSummary?
    @State private var position: MapCameraPosition

    init(
        stations: [StationSummary],
        userCoordinate: CLLocationCoordinate2D,
        cheapestId: String?,
        nearestId: String?,
        selectedFuelType: FuelType
    ) {
        self.stations = stations
        self.userCoordinate = userCoordinate
        self.cheapestId = cheapestId
        self.nearestId = nearestId
        self.selectedFuelType = selectedFuelType
        _position = State(initialValue: .region(MKCoordinateRegion(
            center: userCoordinate,
            latitudinalMeters: 25000,
            longitudinalMeters: 25000
        )))
    }

    var body: some View {
        Map(position: $position) {
            UserAnnotation()
            ForEach(stations) { station in
                let coord = CLLocationCoordinate2D(
                    latitude: station.latitude,
                    longitude: station.longitude
                )
                Annotation("", coordinate: coord, anchor: .bottom) {
                    PricePin(
                        station: station,
                        isCheapest: station.stationId == cheapestId,
                        isNearest: station.stationId == nearestId,
                        isSelected: selectedStation?.stationId == station.stationId
                    )
                    .onTapGesture {
                        withAnimation(.spring(response: 0.3)) {
                            selectedStation = selectedStation?.stationId == station.stationId
                                ? nil : station
                        }
                    }
                }
            }
        }
        .mapControls {
            MapUserLocationButton()
            MapCompass()
        }
        .overlay(alignment: .bottom) {
            if let station = selectedStation {
                StationMapCard(station: station)
                    .padding(.horizontal)
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.3), value: selectedStation?.stationId)
    }
}

// MARK: - Price pin annotation

struct PricePin: View {
    let station: StationSummary
    let isCheapest: Bool
    let isNearest: Bool
    let isSelected: Bool

    private var accentColor: Color {
        if isCheapest { return .green }
        if isNearest { return .blue }
        return .primary
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                Capsule()
                    .fill(isSelected ? accentColor : Color(.systemBackground))
                    .shadow(color: .black.opacity(0.2), radius: isSelected ? 6 : 2, y: 1)
                if let price = station.price {
                    Text(price.formattedPrice)
                        .font(.caption.bold().monospacedDigit())
                        .foregroundStyle(isSelected ? .white : accentColor)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                }
            }
            .overlay(Capsule().stroke(accentColor, lineWidth: 1.5))

            PinTip()
                .fill(isSelected ? accentColor : Color(.systemBackground))
                .overlay(PinTip().stroke(accentColor, lineWidth: 1.5))
                .frame(width: 10, height: 6)
                .offset(y: -1)
        }
        .scaleEffect(isSelected ? 1.15 : 1.0)
        .animation(.spring(response: 0.2), value: isSelected)
    }
}

struct PinTip: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.midX, y: rect.maxY))
            p.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
            p.closeSubpath()
        }
    }
}

// MARK: - Bottom card on pin tap

struct StationMapCard: View {
    let station: StationSummary

    var body: some View {
        NavigationLink(value: station) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(station.tradingName)
                        .font(.subheadline.bold())
                        .foregroundStyle(.primary)
                    Text("\(station.formattedDistance) · \(station.postcode)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let price = station.price {
                    Text(price.formattedPrice)
                        .font(.title3.bold().monospacedDigit())
                        .foregroundStyle(.primary)
                }
                Image(systemName: "chevron.right")
                    .font(.caption.bold())
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
        }
    }
}
