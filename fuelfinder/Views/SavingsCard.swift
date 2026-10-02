import SwiftUI

struct SavingsCard: View {
    let response: FillNowResponse

    private var sameStation: Bool { response.cheapest.id == response.nearest.id }
    private var worthDriving: Bool { response.recommendation.worthDriving && !sameStation }
    private var station: StationSummary { worthDriving ? response.cheapest : response.nearest }

    var body: some View {
        NavigationLink(value: station) {
            VStack(alignment: .leading, spacing: 6) {
                Label(title, systemImage: worthDriving ? "banknote" : "fuelpump.fill")
                    .font(.subheadline.bold())
                Text(station.tradingName)
                    .font(.subheadline)
                if let oldest = response.oldestComparedPrice, response.hasOlderPriceReports {
                    Label("Price reported \(oldest.timeAgo). Check prices before travelling.", systemImage: "clock.badge.exclamationmark")
                        .font(.caption).foregroundStyle(.orange)
                }
                if !sameStation {
                    Text(worthDriving
                         ? "Compared with your nearest station, after estimated extra fuel costs."
                         : response.recommendation.savingPerLitrePence == 0
                            ? "The pump prices are the same, so choose the nearer station."
                            : "The cheaper pump price doesn't cover the estimated extra fuel cost.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Text("Estimate: 40 L fill, 35 mpg (UK), straight-line distances. Actual routes may cost more.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(Color.green.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("savingsRecommendation")
    }

    private var title: String {
        if response.hasOlderPriceReports { return "Savings estimate uses older prices" }
        if sameStation { return "Your nearest station is also the cheapest" }
        if worthDriving {
            let symbol = response.cheapest.price?.currencySymbol ?? "£"
            return String(format: "Save about %@%.2f on a 40 L fill", symbol, Double(response.recommendation.netSavingPence) / 100)
        }
        return "Your nearest station looks better value"
    }
}
