"""City → region (German Bundesland, Austrian Bundesland, Swiss canton) for the index cities."""
R = {
    "Baden-Württemberg": "Stuttgart Karlsruhe Freiburg_im_Breisgau Heidelberg Mannheim Ulm Konstanz Reutlingen Pforzheim Heilbronn Ludwigsburg Friedrichshafen Villingen Sindelfingen Walldorf Esslingen Böblingen Neckarsulm Leinfelden Tübingen",
    "Bayern": "München Nürnberg Augsburg Bayreuth Würzburg Regensburg Ingolstadt Kempten Fürth Bamberg Passau Starnberg Rosenheim Landshut Garching Erlangen Freising Herzogenaurach Dachau Gilching Ismaning Unterföhring",
    "Berlin": "Berlin",
    "Brandenburg": "Potsdam Cottbus",
    "Bremen": "Bremen Bremerhaven",
    "Hamburg": "Hamburg",
    "Hessen": "Frankfurt_am_Main Kassel Wiesbaden Darmstadt Gießen Fulda Rüsselsheim Hanau Wetzlar Marburg Neu-Isenburg Bad_Homburg Offenbach Eschborn Langen",
    "Mecklenburg-Vorpommern": "Rostock Schwerin Neubrandenburg Stralsund Greifswald",
    "Niedersachsen": "Hannover Oldenburg Braunschweig Osnabrück Wolfsburg Göttingen Hildesheim Lingen Lüneburg Salzgitter Wilhelmshaven Emden Celle Wolfenbüttel",
    "Nordrhein-Westfalen": "Köln Düsseldorf Dortmund Bonn Essen Münster Bielefeld Bochum Duisburg Mönchengladbach Aachen Leverkusen Wuppertal Krefeld Hamm Hagen Moers Paderborn Neuss Gelsenkirchen Siegen Oberhausen Ratingen Bottrop Mülheim Bergisch_Gladbach Remscheid Iserlohn Solingen Herne Minden Düren Witten Detmold Recklinghausen Gütersloh",
    "Rheinland-Pfalz": "Mainz Koblenz Kaiserslautern Ludwigshafen Trier",
    "Saarland": "Saarbrücken",
    "Sachsen": "Leipzig Dresden Chemnitz Zwickau Plauen Görlitz",
    "Sachsen-Anhalt": "Magdeburg Halle_(Saale) Dessau",
    "Schleswig-Holstein": "Kiel Lübeck Flensburg Norderstedt",
    "Thüringen": "Erfurt Jena Weimar Gera",
    # Austria
    "Wien": "Wien",
    "Oberösterreich": "Linz Steyr Wels",
    "Salzburg (Land)": "Salzburg",
    "Steiermark": "Graz Leoben",
    "Tirol": "Innsbruck",
    "Vorarlberg": "Feldkirch Dornbirn Bregenz",
    "Kärnten": "Klagenfurt Villach",
    "Niederösterreich": "St._Pölten",
    # Switzerland
    "Kanton Zürich": "Zürich Winterthur",
    "Kanton Bern": "Bern Biel Thun",
    "Kanton Basel-Stadt": "Basel",
    "Kanton St. Gallen": "St._Gallen",
    "Kanton Graubünden": "Chur",
    "Kanton Genf": "Genf",
    "Kanton Luzern": "Luzern",
    "Kanton Aargau": "Aarau",
    "Kanton Tessin": "Lugano",
    "Kanton Waadt": "Lausanne",
    "Kanton Schaffhausen": "Schaffhausen",
    "Kanton Zug": "Zug",
    "Kanton Freiburg": "Fribourg",
}
CITY_REGION = {c.replace("_", " "): r for r, cs in R.items() for c in cs.split()}
REGION_COUNTRY = {r: ("CH" if r.startswith("Kanton") else "AT" if r in ("Wien", "Oberösterreich", "Salzburg (Land)", "Steiermark", "Tirol", "Vorarlberg", "Kärnten", "Niederösterreich") else "DE") for r in R}


def region_of(city, country):
    if city == "Baden":  # ambiguous: Baden bei Wien / Baden AG
        return {"AT": "Niederösterreich", "CH": "Kanton Aargau"}.get(country)
    return CITY_REGION.get(city)
