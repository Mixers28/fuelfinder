import SwiftUI

struct PlaceSearchView: View {
    let onSelect: (SearchLocation) -> Void
    @Environment(\.dismiss) private var dismiss
    @StateObject private var search = PlaceSearch()
    @State private var query = ""
    @State private var country = SearchCountry(rawValue: Locale.current.region?.identifier ?? "") ?? .uk
    @FocusState private var queryFocused: Bool

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Country", selection: $country) {
                        ForEach(SearchCountry.allCases) { country in
                            Text(country.name).tag(country)
                        }
                    }
                    TextField("Town or postcode", text: $query)
                        .textContentType(.addressCityAndState)
                        .submitLabel(.search)
                        .autocorrectionDisabled()
                        .focused($queryFocused)
                        .onSubmit(findPlaces)
                        .accessibilityIdentifier("placeQuery")
                    Button("Search", systemImage: "magnifyingglass", action: findPlaces)
                        .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || search.isSearching)
                        .accessibilityIdentifier("findPlaces")
                } footer: {
                    Text("Search with Apple Maps. No location permission needed.")
                }

                if search.isSearching {
                    ProgressView("Searching places…")
                } else if let message = search.message {
                    Text(message).foregroundStyle(.secondary)
                } else if !search.results.isEmpty {
                    Section("Choose a place") {
                        ForEach(search.results) { location in
                            Button {
                                onSelect(location)
                                dismiss()
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(location.name).foregroundStyle(.primary)
                                    Text(location.subtitle).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Search an area")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onChange(of: query) { search.cancel() }
            .onChange(of: country) { search.cancel() }
            .onAppear { queryFocused = true }
            .onDisappear { search.cancel() }
        }
    }

    private func findPlaces() {
        queryFocused = false
        search.find(query, country: country)
    }
}
