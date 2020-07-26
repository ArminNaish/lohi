import sys
import yaml
import abc
from yaml import Loader
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from prettytable import PrettyTable
from argparse import ArgumentParser


# Altersvermögensgesetz (AVmG)
# Förderung betrieblicher und privater Altersvorsorge
# mithilfe der Riester-Rente, der Entgeltumwandlung sowie
# Regelungen zu förderfähigen Anlagemöglichkeiten
# https://www.steuerklassen.com/lexikon/avmg/

class TaxRate2020:
    def __init__(self, data, anzahl_kinder=0):
        self.werbungskostenpauschale = Decimal(data["freibetrag"]["werbungskostenpauschale"])
        self.sonderausgabenpauschale = Decimal(data["freibetrag"]["sonderausgabenpauschale"])
        self.bemessungsgrenze_rv = Decimal(data["bemessungsgrenze"]["rv"])
        self.bemessungsgrenze_kv = Decimal(data["bemessungsgrenze"]["kv"])
        self.rv_satz = Decimal(data["sozialversicherung"]["rv"])
        self.av_satz = Decimal(data["sozialversicherung"]["av"])
        self.pv_satz = Decimal(data["sozialversicherung"]["pv"])
        self.soli_satz = Decimal(data["steuer"]["soli"])
        self.kv_satz_reduziert = Decimal(data["sozialversicherung"]["kv_red"])
        self.kv_zusatzbeitrag = Decimal(data["sozialversicherung"]["kv_zb"])
        self.grundfreibetrag = Decimal(data["freibetrag"]["grundfreibetrag"])
        self.kinderfreibetrag = Decimal(data["freibetrag"]["kinderfreibetrag"])
        self.eingetragener_freibetrag = Decimal(data["freibetrag"]["eingetragenerfreibetrag"])
        self.vsp_korrekturfaktor = Decimal(data["vorsorgepauschale"]["korrekturfaktor"])
        self.vsp_mindestsatz = Decimal(data["vorsorgepauschale"]["mindestsatz"])
        self.vsp_hoechstbetrag = Decimal(data["vorsorgepauschale"]["hoechstbetrag"])
        self.anzahl_kinder = anzahl_kinder

    def calculate_lohnsteuer(self, steuer_brutto):
        # Vorsorgepauschale mit Teilbeträgen für die Rentenversicherung
        # sowie die gesetzliche Kranken- und soziale Pflegeversicherung nach
        vsp = self.calculate_vorsorgekostenpauschaule(steuer_brutto)
        kfb = self.kinderfreibetrag * self.anzahl_kinder
        
        # Zu versteuerndes Einkommen ohne Freibeträge
        zvE = steuer_brutto * 12
        zvE = zvE - self.werbungskostenpauschale
        zvE = zvE - self.sonderausgabenpauschale
        zvE = zvE - vsp
        zvE = zvE - kfb
        zvE = zvE - self.eingetragener_freibetrag

        if zvE <= self.grundfreibetrag:
            lohnsteuer = self.zone1(zvE) / 12
        elif self.grundfreibetrag < zvE <= 14533:
            lohnsteuer = self.zone2(zvE) / 12
        elif 14533 < zvE <= 57052:
            lohnsteuer = self.zone3(zvE) / 12
        elif 57052 < zvE <= 270501:
            lohnsteuer = self.zone4(zvE) / 12
        else:
            lohnsteuer = self.zone5(zvE) / 12

        return lohnsteuer

    def calculate_vorsorgekostenpauschaule(self, steuer_brutto):
        vsp1 = self.calculate_vsp1(steuer_brutto)
        vsp2 = self.calculate_vsp2(steuer_brutto)
        vsp3 = self.calculate_vsp3(steuer_brutto)
        """
        Vergleichsrechnung:
        Da die Vorsorgepauschale aus Nr. 1 + Nr. 3 höher ist als aus Nr. 1 + Nr. 2,
        wird der höhere Betrag angesetzt:
        Die Vorsorgepauschale für 2019 beträgt also im Beispiel 2.120,40 Euro + 2.692,50 Euro
        = 4.813 Euro (aufgerundet).
        """
        vspn = round_up_to_euro(vsp1 + vsp2)
        vsp = round_up_to_euro(vsp3 + vsp1)
        if vspn > vsp:
            vsp = vspn
        return vsp

    def calculate_vsp1(self, steuer_brutto):
        """
        1.) Teil-Vorsorgepauschale für Rentenversicherung
            → 30.000 Euro × 0,093  (halber RV-Beitrag von 18,6 %)
            = 2.790 Euro davon 76 % im Jahr 2019 (in jedem weiteren Jahr vier Prozentpunkte mehr)
            = 2.120,40 Euro
        """
        jahres_brutto = steuer_brutto * 12
        jahres_bbgr_rv = self.bemessungsgrenze_rv * 12
        if jahres_brutto > jahres_bbgr_rv:
            jahres_brutto = jahres_bbgr_rv

        rv_satz = self.rv_satz
        value = jahres_brutto / 100 * Decimal(rv_satz)
        return value / 100 * self.vsp_korrekturfaktor

    def calculate_vsp2(self, steuer_brutto):
        """
        2.) Teil-Vorsorgepauschale für Kranken- und Pflegeversicherung
            Mindestansatz
                12 % des Arbeitslohns (30.000 Euro × 0,12 = 3.600 Euro)
                jedoch höchstens 1.900 Euro (bei Unverheirateten)
                = 1.900 Euro
        """
        jahres_brutto = steuer_brutto * 12
        value = jahres_brutto / 100 * self.vsp_mindestsatz
        if value > self.vsp_hoechstbetrag:
            value = self.vsp_hoechstbetrag
        return value

    def calculate_vsp3(self, steuer_brutto):
        """
        3.) Teil-Vorsorgepauschale für Kranken- und Pflegeversicherung
            Arbeitnehmeranteil bei gesetzlich Versicherten
                für Krankenversicherung 7,45 %
                (verminderter Beitragssatz Basisversorgung 7,0 % + 0,45 % (halber Zusatzbeitrag von 0,9 %)) und
                für Pflegeversicherung 1,525 %
                = insgesamt 8,975 %
                8,975 % von 30.000 Euro = 2.692,50 Euro
        """
        jahres_brutto = steuer_brutto * 12
        jahres_bbgr_kv = self.bemessungsgrenze_kv * 12
        if jahres_brutto > jahres_bbgr_kv:
            jahres_brutto = jahres_bbgr_kv

        kv_pv_satz =  self.kv_satz_reduziert + (self.kv_zusatzbeitrag / 2) + self.pv_satz
        vsp = jahres_brutto / 100 * Decimal(kv_pv_satz)
        return vsp

    def zone1(self, zvE):
        return 0

    def zone2(self, zvE):
        y = (zvE - self.grundfreibetrag) / Decimal(10000)
        value = (Decimal(972.87) * y + Decimal(1400)) * y
        return round_down_to_euro(value)

    def zone3(self, zvE):
        z = (zvE - 14532) / 10000
        value = (212.02 * z + 2397) * z + Decimal(972.79)
        return round_down_to_euro(value)

    def zone4(self, zvE):
        value = Decimal(0.42) * zvE - Decimal(8963.74)
        return round_down_to_euro(value)

    def zone5(self, zvE):
        value = Decimal(0.45) * zvE - Decimal(17078.74)
        return round_down_to_euro(value)


class Payslip:
    def __init__(self, tax_rate):
        self.tax_rate = tax_rate

    def calculate(self, monatsentgelt, pk_hoeherversicherung, pk_entgeltumwandlung, urlaubsgeld):
        # Entgeltbestandteile
        monatsentgelt = Decimal(monatsentgelt)
        pk_hoeherversicherung = Decimal(pk_hoeherversicherung)
        pk_entgeltumwandlung = Decimal(pk_entgeltumwandlung)
        urlaubsgeld = Decimal(urlaubsgeld)
        betriebliche_leistung = pk_entgeltumwandlung + urlaubsgeld
        gehalt = monatsentgelt - betriebliche_leistung
        avmg_kuerzung_sv_frei = pk_hoeherversicherung

        # Bruttoentgelte
        gesamt_brutto = gehalt + betriebliche_leistung
        steuer_brutto = gesamt_brutto - avmg_kuerzung_sv_frei
        sv_brutto_kv_pv = self.tax_rate.bemessungsgrenze_kv if steuer_brutto > self.tax_rate.bemessungsgrenze_kv else steuer_brutto
        sv_brutto_rv_av = self.tax_rate.bemessungsgrenze_rv if steuer_brutto > self.tax_rate.bemessungsgrenze_rv else steuer_brutto

        # Gesetzliche Abzüge
        lohnsteuer = round_down_to_cent(self.tax_rate.calculate_lohnsteuer(steuer_brutto))
        soli = round_down_to_cent(lohnsteuer / 100 * self.tax_rate.soli_satz)
        rv = sv_brutto_rv_av / 100 * self.tax_rate.rv_satz
        av = sv_brutto_rv_av / 100 * self.tax_rate.av_satz
        netto = gesamt_brutto - lohnsteuer - soli - rv - av

        # Sonstige Be-/Abzüge
        # ...
        # Zusatzversorgung
        # ...

        self.monatsentgelt = monatsentgelt
        self.betriebliche_leistung = betriebliche_leistung
        self.gehalt = gehalt
        self.avmg_kuerzung_sv_frei = avmg_kuerzung_sv_frei
        self.gesamt_brutto = gesamt_brutto
        self.steuer_brutto = steuer_brutto
        self.sv_brutto_kv_pv  = sv_brutto_kv_pv 
        self.sv_brutto_rv_av = sv_brutto_rv_av
        self.lohnsteuer = lohnsteuer
        self.soli = soli 
        self.rv = rv
        self.av = av
        self.netto = netto

    def print(self):
        report = PrettyTable(["Position", "", "Monat"])
        report.align["Position"] = "l"
        report.align[""] = "r"
        report.align["Monat"] = "r"
        report.add_row(["Vereinb. Montagsentgelt", str(money(self.monatsentgelt)), ""])
        report.add_row(["Gehalt", "", str(money(self.gehalt))])
        report.add_row(["Betriebliche Leistung", "", str(money(self.betriebliche_leistung))])
        report.add_row(["AVmG Kürzung lfd. SV-frei","-" + str(money(self.avmg_kuerzung_sv_frei)),""])
        report.add_row(["Gesamtbrutto", "", str(money(self.gesamt_brutto))])
        report.add_row(["Steuer-Brutto", str(money(self.steuer_brutto)), ""])
        report.add_row(["SV-Brutto KV/PV", str(money(self.sv_brutto_kv_pv)), ""])
        report.add_row(["SV-Brutto RV/AV", str(money(self.sv_brutto_rv_av)), ""])
        report.add_row(["Lohnsteuer", "", str(money(self.lohnsteuer))])
        report.add_row(["Solidaritätszuschlag", "", str(money(self.soli))])
        report.add_row(["Rentenversicherung", "", str(money(self.rv))])
        report.add_row(["Arbeitslosenversicherung", "", str(money(self.av))])
        report.add_row(["Gesetzliches Netto", "", str(money(self.netto))])
        print(report)


def main():
    args = parse_arguments()
    data = read_yml_file(args.tariff)
    taxrate = TaxRate2020(data)
    payslip = Payslip(taxrate)
    payslip.calculate(
        args.monatsentgelt, 
        args.hoeherversicherung, 
        args.entgeltumwandlung,
        args.urlaubsgeld
    )
    payslip.print()


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument(
        "--tariff",
        dest="tariff",
        help="read tariff from yaml file",
        metavar="FILE",
    )
    parser.add_argument(
        "--monatsentgelt",
        dest="monatsentgelt",
        help="Monatliches Bruttogehalt"
    )
    parser.add_argument(
        "--hoeherversicherung",
        dest="hoeherversicherung",
        help="Monatlicher Betreig für freiwillige Hoeherversicherung an Pensionskasse (pk+)"
    )
    parser.add_argument(
        "--entgeltumwandlung",
        dest="entgeltumwandlung",
        help="Monatliche Entgeltumwandlung an Pensionskasse"
    )
    parser.add_argument(
        "--urlaubsgeld",
        dest="urlaubsgeld",
        help="Monatliches Urlaubsgeld"
    )
    return parser.parse_args()


def read_yml_file(fpath):
    try:
        with open(fpath, "r") as file:
            return yaml.load(file, Loader=Loader)
    except OSError:
        print(f"Could not open/read file: {fpath}")
        sys.exit()


def money(value):
    return round_decimal(Decimal(value))


def round_up_to_euro(value):
    return value.quantize(Decimal("1"), rounding=ROUND_UP)


def round_down_to_euro(value):
    return value.quantize(Decimal("1"), rounding=ROUND_DOWN)


def round_down_to_cent(value):
    return value.quantize(Decimal(".01"), rounding=ROUND_DOWN)


def round_decimal(value):
    return value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


if __name__ == "__main__":
    main()
