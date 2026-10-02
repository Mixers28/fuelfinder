import XCTest

final class FuelFinderUITests: XCTestCase {
    @MainActor
    func testSearchAndFavouritesWorkWithoutLocationAndFuelChoicePersists() throws {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["searchArea"].waitForExistence(timeout: 10))
        app.segmentedControls.buttons["Diesel"].tap()
        app.buttons["searchArea"].tap()
        XCTAssertTrue(app.textFields["placeQuery"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Search with Apple Maps. No location permission needed."].exists)
        app.buttons["Cancel"].tap()
        app.buttons["openFavourites"].tap()
        XCTAssertTrue(app.navigationBars["Favourites"].waitForExistence(timeout: 5))
        app.buttons["Done"].tap()
        app.terminate()
        app.launch()
        XCTAssertTrue(app.segmentedControls.buttons["Diesel"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.segmentedControls.buttons["Diesel"].isSelected)
    }
}
