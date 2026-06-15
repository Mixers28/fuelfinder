import SwiftUI

struct StationDetailView: View {
    let stationId: String
    let fuelType: FuelType
    
    @State private var detail: StationDetail?
    @State private var fillNow: FillNowResponse?
    @State private var isLoading = true
    @State private var errorMessage: String?
    
    var body: some View {
        ScrollView {
            if isLoading {
                ProgressView()
                    .padding(.top, 40)
            } else if let error = errorMessage {
                Text(error)
                    .foregroundStyle(.secondary)
                    .padding()
            } else if let detail {
                content(detail)
            }
        }
        .navigationTitle(detail?.tradingName ?? "Station")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadData() }
    }
    
    // MARK: - Content
    
    @ViewBuilder
    private func content(_ station: StationDetail) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            // Address
            VStack(alignment: .leading, spacing: 4) {
                Text(station.address)
                    .font(.subheadline)
                Text(station.postcode)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if let brand = station.brand {
                    Text(brand)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal)
            
            // All fuel prices
            VStack(alignment: .leading, spacing: 8) {
                Text("Fuel Prices")
                    .font(.headline)
                
                ForEach(station.prices) { price in
                    HStack {
                        Circle()
                            .fill(colorForFuel(price.fuelType))
                            .frame(width: 8, height: 8)
                        Text(price.fuelType.displayName)
                            .font(.subheadline)
                        Spacer()
                        Text(price.formattedPrice)
                            .font(.subheadline.bold().monospacedDigit())
                        Text(price.timeAgo)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.vertical, 4)
                    
                    if price.id != station.prices.last?.id {
                        Divider()
                    }
                }
            }
            .padding()
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal)
            
            // Worth it recommendation
            if let rec = fillNow?.recommendation {
                worthItCard(rec)
                    .padding(.horizontal)
            }
            
            // Amenities
            if !station.amenities.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Amenities")
                        .font(.headline)
                    
                    FlowLayout(spacing: 8) {
                        ForEach(station.amenities, id: \.self) { amenity in
                            Text(amenityLabel(amenity))
                                .font(.caption)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 6)
                                .background(.regularMaterial)
                                .clipShape(Capsule())
                        }
                    }
                }
                .padding(.horizontal)
            }
        }
        .padding(.vertical)
    }
    
    // MARK: - Worth It Card
    
    private func worthItCard(_ rec: WorthItRecommendation) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: rec.worthDriving ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(rec.worthDriving ? .green : .red)
                Text(rec.worthDriving ? "Worth the drive" : "Not worth the drive")
                    .font(.subheadline.bold())
            }
            
            Text(rec.explanation)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(rec.worthDriving ? Color.green.opacity(0.08) : Color.red.opacity(0.08))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(rec.worthDriving ? Color.green.opacity(0.3) : Color.red.opacity(0.3), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
    
    // MARK: - Helpers
    
    private func colorForFuel(_ type: FuelType) -> Color {
        switch type {
        case .E10: return .green
        case .E5: return .blue
        case .B7: return .orange
        case .SDV: return .purple
        }
    }
    
    private func amenityLabel(_ key: String) -> String {
        switch key {
        case "shop": return "🏪 Shop"
        case "atm": return "🏧 ATM"
        case "air": return "💨 Air"
        case "car_wash": return "🚗 Car wash"
        default: return key.capitalized
        }
    }
    
    private func loadData() async {
        do {
            async let detailTask = FuelFinderAPI.shared.stationDetail(stationId: stationId)
            // fillNow needs location — in production, pass from parent
            detail = try await detailTask
            isLoading = false
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }
}

// MARK: - Flow Layout (simple horizontal wrap)

struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }
    
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, position) in result.positions.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y), proposal: .unspecified)
        }
    }
    
    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var maxX: CGFloat = 0
        
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            maxX = max(maxX, x)
        }
        
        return (CGSize(width: maxX, height: y + rowHeight), positions)
    }
}
