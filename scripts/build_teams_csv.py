"""Generate data/teams.csv from data/Test.csv.

Feed-name overrides cover countries whose ESPN / Football-Data display name
differs from the Zindi `country` value. VERIFY each row against the live feeds
before trusting (see Task 7 verification step).
"""
import csv

# country -> (espn_name, fd_name); default is country itself.
OVERRIDES = {
    "Czechia": ("Czech Republic", "Czech Republic"),
    "Turkiye": ("Turkey", "Türkiye"),
    "Cote d'Ivoire": ("Ivory Coast", "Côte d'Ivoire"),
    "DR Congo": ("Congo DR", "DR Congo"),
    "South Korea": ("South Korea", "Korea Republic"),
    "Cabo Verde": ("Cape Verde", "Cabo Verde"),
    "Curacao": ("Curaçao", "Curaçao"),
    "United States": ("United States", "United States"),
}


def main() -> None:
    rows = []
    with open("data/Test.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            zid = r["ID"].strip()
            country = r["country"].strip()
            iso3 = zid.split("_")[-1]
            espn, fd = OVERRIDES.get(country, (country, country))
            rows.append((zid, country, iso3, espn, fd))
    with open("data/teams.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zindi_id", "country", "iso3", "espn_name", "fd_name"])
        w.writerows(rows)
    print(f"wrote {len(rows)} teams")


if __name__ == "__main__":
    main()
