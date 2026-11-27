"""Melderegeln und Verlauf: Was wird wann gemeldet, was nicht."""
import unittest
from datetime import timedelta

from blackout_radar import areas, simulate
from blackout_radar.engine import Engine
from blackout_radar.model import Signal, parse_ts

from .helpers import T0, at, frequency, internet, load, make_cfg, media, play, utility


def confirmed(area, since, now, active=True):
    """Von der Quelle selbst als Stromausfall eingestuft (z. B. Cloudflare Radar)."""
    return Signal("cloudflare", "confirmed_outage", area, observed_at=now, active=active,
                  severity=0.5 if active else 0.0, started_at=since, ended_at=None if active else now,
                  confirmed_power=True, detail="Cloudflare Radar bestätigt Stromausfall, landesweit")


def news(area, title, domain, now):
    return Signal("news", "news", area, observed_at=now, active=False, detail=title,
                  url=f"https://{domain}/a", metrics={"domain": domain, "power": True})


def titles(sent):
    return [message.title for _, message in sent]


class WorldFilter(unittest.TestCase):
    """Rest der Welt: erst ab 30 Minuten, ab Mindestgröße und nur mit belegter Ursache."""

    def setUp(self):
        self.engine = Engine(make_cfg(), {})

    def test_short_outage_is_not_reported(self):
        def script(minute, now):
            if minute <= 20:
                return [internet("ES", 0.6, at(0), now), confirmed("ES", at(0), now)]
            if minute == 25:
                return [internet("ES", 0.6, at(0), now, active=False), confirmed("ES", at(0), now, active=False)]
            return []

        self.assertEqual(play(self.engine, script, 120), [])

    def test_long_outage_is_reported_after_30_minutes(self):
        sent = play(self.engine, lambda minute, now: [internet("ES", 0.6, at(0), now), confirmed("ES", at(0), now)], 45)
        self.assertEqual([minute for minute, _ in sent], [30])
        message = sent[0][1]
        self.assertEqual(message.title, "Blackout: Spanien")
        self.assertEqual(message.level, "info")  # weit weg: normale Dringlichkeit
        self.assertIn("Seit 12:00 Uhr", message.body)

    def test_unconfirmed_outage_is_not_reported(self):
        sent = play(self.engine, lambda minute, now: [internet("ES", 0.6, at(0), now)], 120)
        self.assertEqual(sent, [])
        event = next(iter(self.engine.state["events"].values()))
        self.assertIn("Strom als Ursache nicht bestätigt", self.engine.hold_reasons(event, at(120)))

    def test_small_outage_is_not_reported(self):
        sent = play(self.engine, lambda minute, now: [load("ES", 0.005, at(-60), now),
                                                      media("ES", 0.005, at(-60), now)], 60)
        self.assertEqual(sent, [])
        event = next(iter(self.engine.state["events"].values()))
        self.assertEqual(self.engine.hold_reasons(event, at(60)), ["zu klein für eine Meldung"])

    def test_neighbour_country_is_a_warning(self):
        sent = play(self.engine, lambda minute, now: [load("CZ", 0.6, at(-60), now), media("CZ", 0.5, at(-60), now)], 10)
        self.assertEqual(sent[0][1].title, "Blackout: Tschechien")
        self.assertEqual(sent[0][1].level, "warn")

    def test_media_only_world_event(self):
        def script(minute, now):
            if minute <= 300:
                return [media("CU", 0.5, at(-10), now, text="5 Medien berichten, landesweiter Ausfall laut Schlagzeilen"),
                        news("CU", "Colapso total del sistema eléctrico en Cuba", "example.cu", at(-10))]
            if minute == 305:
                return [media("CU", None, at(-10), now, active=False)]
            return []

        sent = play(self.engine, script, 420)
        self.assertEqual([minute for minute, _ in sent], [20])  # 30 Minuten nach dem ersten Bericht
        message = sent[0][1]
        self.assertEqual(message.title, "Blackout: Kuba (laut Medien)")
        self.assertEqual(message.level, "info")
        self.assertTrue(message.body.startswith("» Colapso total del sistema eléctrico en Cuba (example.cu)"))
        self.assertIn("Dauer und Ende lassen sich aus Medienberichten nicht ablesen", message.body)

    def test_ignored_areas_never_create_events(self):
        cfg = make_cfg()
        cfg["filter"]["ignore_areas"] = ["UA"]
        engine = Engine(cfg, {})
        sent = play(engine, lambda minute, now: [media("UA", 0.5, at(-60), now), media("UA-43", 0.5, at(-60), now)], 60)
        self.assertEqual(sent, [])
        self.assertEqual(engine.state["events"], {})


class PriorityAreas(unittest.TestCase):
    """Oberösterreich: jedes Signal sofort. Österreich: sofort ab einem großen Ausfall."""

    def setUp(self):
        self.engine = Engine(make_cfg(), {})

    def test_upper_austria_is_reported_immediately_even_if_small(self):
        def script(minute, now):
            if minute <= 60:
                return [media("AT-4", 0.026, at(-10), now, text="1 Medium berichtet, rund 40.000 Betroffene")]
            if minute == 65:
                return [media("AT-4", None, at(-10), now, active=False)]
            return []

        sent = play(self.engine, script, 180)
        self.assertEqual([minute for minute, _ in sent], [0])
        self.assertEqual(sent[0][1].title, "Stromausfall: Oberösterreich (laut Medien)")
        self.assertEqual(sent[0][1].level, "warn")  # klein: hohe Dringlichkeit, aber kein Alarm
        # Medien allein belegen kein Ende: keine Entwarnung
        self.assertFalse(any("Entwarnung" in title for title in titles(sent)))

    def test_small_outage_elsewhere_in_austria_is_only_watched(self):
        sent = play(self.engine, lambda minute, now: [media("AT", 0.004, at(-10), now)], 120)
        self.assertEqual(sent, [])
        event = next(iter(self.engine.state["events"].values()))
        self.assertEqual(self.engine.hold_reasons(event, at(120)), ["zu klein für eine Meldung"])

    def test_large_outage_in_austria_is_an_alarm(self):
        sent = play(self.engine, lambda minute, now: [media("AT", 0.5, at(-5), now)], 0)
        self.assertEqual(sent[0][1].title, "Blackout: Österreich (laut Medien)")
        self.assertEqual(sent[0][1].level, "alarm")
        self.assertIn("Richtwert der APG", sent[0][1].body)

    def test_grid_operator_report_gets_start_and_all_clear(self):
        def script(minute, now):
            if minute <= 10:
                return [utility("AT-4", at(0), now)]
            if minute == 15:
                return [utility("AT-4", at(0), now, active=False)]
            return []

        sent = play(self.engine, script, 60)
        self.assertEqual(titles(sent), ["Stromausfall: Oberösterreich", "Entwarnung: Oberösterreich (Dauer 15 min)"])
        self.assertEqual([minute for minute, _ in sent], [0, 30])  # Entwarnung erst nach 15 ruhigen Minuten
        self.assertEqual(sent[1][1].level, "ok")

    def test_relapse_is_reported(self):
        def script(minute, now):
            if minute <= 10 or 60 <= minute <= 70:
                return [utility("AT-4", at(0), now)]
            if minute in (15, 75):
                return [utility("AT-4", at(0), now, active=False)]
            return []

        sent = play(self.engine, script, 120)
        self.assertEqual(titles(sent)[:3], ["Stromausfall: Oberösterreich", "Entwarnung: Oberösterreich (Dauer 15 min)",
                                            "Update Oberösterreich: erneut ausgefallen"])
        self.assertTrue(titles(sent)[3].startswith("Entwarnung: Oberösterreich"))

    def test_silent_source_is_not_an_all_clear(self):
        sent = play(self.engine, lambda minute, now: [utility("AT-4", at(0), now)] if minute <= 10 else [], 300)
        self.assertEqual(titles(sent)[0], "Stromausfall: Oberösterreich")
        self.assertEqual(titles(sent)[-1], "Keine Daten mehr: Oberösterreich")
        self.assertIn("Das ist keine Entwarnung", sent[-1][1].body)
        self.assertFalse(any(title.startswith("Entwarnung") for title in titles(sent)))

    def test_all_clear_from_a_source_that_never_reported_is_ignored(self):
        self.engine.tick([media("AT-4", 0.02, at(-5), at(0))], at(0))
        self.engine.tick([media("AT-4", 0.02, at(-5), at(5)), internet("AT-4", None, at(0), at(5), active=False)], at(5))
        incident = next(iter(self.engine.state["events"].values()))["incidents"]["AT-4"]
        self.assertIsNone(incident["ended_at"])
        self.assertEqual(list(incident["sources"]), ["media"])

    def test_new_area_is_only_news_if_it_matters(self):
        def script(minute, now):
            signals = [media("AT-4", 0.02, at(-5), now)]
            if minute >= 10:
                signals.append(media("AT", 0.5 if minute >= 30 else 0.004, at(5), now))
            return signals

        sent = play(self.engine, script, 45)
        self.assertEqual([minute for minute, _ in sent], [0, 30])
        self.assertEqual(sent[1][1].title, "Update Oberösterreich, Österreich: jetzt als Blackout eingestuft")
        self.assertEqual(sent[1][1].level, "alarm")

    def test_unconfirmed_drop_becomes_confirmed_by_media(self):
        def script(minute, now):
            signals = [internet("AT", 0.5, at(0), now)]
            if minute >= 5:
                signals += [news("AT", "Blackout: Ganz Österreich ohne Strom", "orf.at", at(4)),
                            news("AT", "Stromausfall legt Österreich lahm", "derstandard.at", at(4))]
            return signals

        sent = play(self.engine, script, 15)
        self.assertEqual(titles(sent), ["Verdacht auf Stromausfall: Österreich",
                                        "Update Österreich: Strom als Ursache bestätigt"])
        self.assertIn("» Blackout: Ganz Österreich ohne Strom (orf.at)", sent[1][1].body)

    def test_too_many_messages_per_hour_are_held_back(self):
        neighbours = ["DE", "CZ", "HU", "SK", "SI"]

        def script(minute, now):
            signals = [media("AT-4", 0.02, at(-5), now)]
            signals += [media(area, 0.5, at(5 * index), now) for index, area in enumerate(neighbours, 1)
                        if minute >= 5 * index]
            return signals

        sent = play(self.engine, script, 60)
        self.assertEqual([minute for minute, _ in sent], [0, 5, 10, 15, 60])
        self.assertTrue(sent[1][1].title.startswith("Update Oberösterreich, Deutschland: jetzt als Blackout"))
        self.assertTrue(sent[4][1].title.endswith("Ausbreitung"))


class LoadData(unittest.TestCase):
    """Lastdaten allein reichen nur bei einem massiven, anhaltenden Einbruch im Vorrang-Gebiet."""

    def setUp(self):
        self.engine = Engine(make_cfg(), {})

    def test_moderate_drop_alone_is_not_reported(self):
        sent = play(self.engine, lambda minute, now: [load("AT", 0.25, at(-240), now - timedelta(minutes=135))], 120)
        self.assertEqual(sent, [])
        event = next(iter(self.engine.state["events"].values()))
        self.assertEqual(self.engine.hold_reasons(event, at(120)), ["nur Lastdaten, kein zweites Signal"])

    def test_massive_drop_alone_is_reported_once_it_lasts(self):
        # Beginn in den Daten um 09:30 UTC, die Daten sind 135 Minuten alt
        sent = play(self.engine, lambda minute, now: [load("AT", 0.45, at(-150), now - timedelta(minutes=135))], 30)
        self.assertEqual([minute for minute, _ in sent][:1], [15])  # erst bei 30 Minuten Daten im Einbruch
        self.assertEqual(sent[0][1].title, "Großer Stromausfall: Österreich")
        self.assertEqual(sent[0][1].level, "alarm")

    def test_drop_alone_outside_priority_area_is_never_reported(self):
        sent = play(self.engine, lambda minute, now: [load("CZ", 0.8, at(-240), now - timedelta(minutes=135))], 180)
        self.assertEqual(sent, [])

    def test_single_headlines_do_not_turn_a_drop_into_an_outage(self):
        # Lokale Ausfälle gibt es in jedem Land täglich. Zwei Schlagzeilen belegen keinen landesweiten Einbruch.
        def script(minute, now):
            signals = [load("DE", 0.3, at(-240), now - timedelta(minutes=135))]
            if minute == 10:
                signals += [Signal("news", "news", "DE", observed_at=now, active=False, detail=title,
                                   url=f"https://{domain}/1", metrics={"domain": domain, "power": True, "lead": True})
                            for title, domain in (("Stromausfall in Berlin-Köpenick", "a.example"),
                                                  ("Stromausfall in München-Schwabing", "b.example"))]
            return signals

        self.assertEqual(play(self.engine, script, 180), [])

    def test_drop_with_a_media_story_is_reported(self):
        def script(minute, now):
            return [load("DE", 0.3, at(-240), now - timedelta(minutes=135)), media("DE", 0.2, at(-200), now)]

        sent = play(self.engine, script, 30)
        self.assertEqual(titles(sent)[:1], ["Großer Stromausfall: Deutschland"])

    def test_media_story_lingering_after_measured_end_opens_nothing_new(self):
        def script(minute, now):
            signals = [media("AT", 0.5, at(-20), now)]
            if minute <= 60:
                signals.append(load("AT", 0.5, at(-60), now - timedelta(minutes=30)))
            elif minute == 65:
                signals.append(load("AT", 0.5, at(-60), now - timedelta(minutes=30), active=False))
            return signals

        sent = play(self.engine, script, 400)
        self.assertEqual(titles(sent)[0], "Blackout: Österreich")
        self.assertTrue(titles(sent)[-1].startswith("Entwarnung: Österreich (Dauer 1 h 35 min)"))
        self.assertEqual(sent[-1][0], 65)
        self.assertEqual(len(self.engine.state["events"]), 1)

    def test_areas_waiting_for_media_confirmation(self):
        self.engine.tick([internet("AT", 0.5, at(0), at(0)), media("DE", 0.5, at(0), at(0))], at(0))
        self.assertEqual(self.engine.active_areas(), ["AT"])


class EuropeWide(unittest.TestCase):
    """Schlagzeilen, die nur "Europa" nennen: So berichten Medien in Übersee, wenn der Kontinent betroffen ist."""

    def setUp(self):
        self.engine = Engine(make_cfg(), {})

    def test_blackout_across_europe_is_an_alarm_at_once(self):
        text = "3 Medien berichten, europaweiter Ausfall laut Schlagzeilen"
        sent = play(self.engine, lambda minute, now: [media("EU", 0.5, at(-20), now, text=text)], until=0)
        self.assertEqual(titles(sent), ["Blackout: Europa (laut Medien)"])
        message = sent[0][1]
        self.assertEqual(message.level, "alarm")
        self.assertIn("• Europa: 3 Medien berichten, europaweiter Ausfall laut Schlagzeilen", message.body)
        self.assertIn("Richtwert der APG", message.body)  # das eigene Land liegt in Europa

    def test_smaller_outage_somewhere_in_europe_follows_the_world_rules(self):
        share = 2_000_000 / 450_000_000  # "Millions without power as blackout hits Balkans"
        sent = play(self.engine, lambda minute, now: [media("EU", share, at(0), now)], until=60)
        self.assertEqual([(minute, message.title, message.level) for minute, message in sent],
                         [(30, "Stromausfall: Europa (laut Medien)", "warn")])

    def test_europe_of_unknown_size_is_only_watched(self):
        sent = play(self.engine, lambda minute, now: [media("EU", None, at(0), now)], until=120)
        self.assertEqual(sent, [])
        event = next(iter(self.engine.state["events"].values()))
        self.assertIn("Größe unbekannt", self.engine.hold_reasons(event, at(120)))

    def test_europe_and_its_countries_are_one_event_and_people_count_once(self):
        def script(minute, now):
            signals = [media("EU", 0.5, at(0), now)]
            if minute >= 5:
                signals.append(media("AT", 0.5, at(5), now))
            if minute >= 10:
                signals.append(media("US", 0.01, at(10), now))  # gehört nicht dazu
            return signals

        sent = play(self.engine, script, until=10)
        events = sorted(self.engine.state["events"].values(), key=lambda event: event["started_at"])
        self.assertEqual([sorted(event["incidents"]) for event in events], [["AT", "EU"], ["US"]])
        self.assertEqual(self.engine.impact(events[0]), 225_000_000)  # Österreich steckt in "Europa"
        self.assertEqual(titles(sent)[0], "Blackout: Europa (laut Medien)")
        self.assertIn("Blackout: Österreich, Europa (laut Medien)", self.engine.headline(events[0]))

    def test_related_areas(self):
        self.assertTrue(areas.related("EU", "AT-4") and areas.related("ES", "EU") and areas.related("EU", "EU"))
        self.assertFalse(areas.related("EU", "US") or areas.related("EU", "UA") or areas.related("RU", "EU"))
        self.assertTrue(areas.related("AT", "DE") and not areas.related("AT", "ES"))  # Nachbarn wie bisher
        self.assertEqual((areas.name("EU"), areas.population("EU")), ("Europa", 450_000_000))

    def test_far_away_home_does_not_treat_europe_as_its_own(self):
        cfg = make_cfg()
        cfg["priority"].update({"areas": ["US"], "always_areas": []})
        engine = Engine(cfg, {})
        sent = play(engine, lambda minute, now: [media("EU", 0.5, at(0), now)], until=40)
        self.assertEqual([(minute, message.level) for minute, message in sent], [(30, "info")])


class Frequency(unittest.TestCase):
    def test_alarm_and_all_clear(self):
        engine = Engine(make_cfg(), {})

        def script(minute, now):
            if minute <= 5:
                return [frequency(49.7, at(0), now)]
            return [frequency(None, at(0), now)] if minute == 10 else []

        sent = play(engine, script, 40)
        self.assertEqual([minute for minute, _ in sent], [0, 25])
        self.assertEqual(sent[0][1].title, "Netzfrequenz-Alarm: 49,70 Hz")
        self.assertEqual(sent[0][1].level, "warn")
        self.assertTrue(sent[1][1].title.startswith("Netzfrequenz wieder normal: 50,00 Hz"))


class Simulation(unittest.TestCase):
    """Das Planspiel ist zugleich der Gesamttest für einen Blackout in Österreich."""

    @classmethod
    def setUpClass(cls):
        cls.sent = simulate.run(make_cfg(), T0 - timedelta(hours=6))  # 06:00 Uhr in Wien
        cls.titles = [message.title for _, message in cls.sent]

    def test_order_of_messages(self):
        self.assertEqual(self.titles[0], "Netzfrequenz-Alarm: 49,31 Hz")
        self.assertEqual(self.titles[1], "Stromausfall: Oberösterreich (laut Medien)")
        self.assertIn("Update Oberösterreich, Österreich: jetzt als Blackout eingestuft", self.titles)
        self.assertIn("Update Oberösterreich, Österreich, Tschechien: Messwerte liegen vor", self.titles)
        self.assertIn("Update Oberösterreich, Österreich, Tschechien: Wiederherstellung", self.titles)
        self.assertEqual(self.titles[-1], "Entwarnung: Oberösterreich, Österreich, Tschechien (Dauer 10 h 40 min)")

    def test_exactly_one_all_clear_with_restoration_order(self):
        clear = [message for _, message in self.sent if message.title.startswith("Entwarnung")]
        self.assertEqual(len(clear), 1)
        self.assertIn("Reihenfolge der Wiederversorgung: Tschechien 07:45 → Österreich 16:45", clear[0].body)
        self.assertIn("Verlauf: 06:05 Österreich → 06:05 Tschechien → 06:20 Oberösterreich (Medienbericht)", clear[0].body)

    def test_alarm_levels(self):
        levels = {message.title: message.level for _, message in self.sent}
        self.assertEqual(levels["Netzfrequenz-Alarm: 49,31 Hz"], "alarm")
        self.assertEqual(levels["Stromausfall: Oberösterreich (laut Medien)"], "warn")
        self.assertEqual(levels["Update Oberösterreich, Österreich: jetzt als Blackout eingestuft"], "alarm")

    def test_message_keys_are_unique(self):
        keys = [message.key for _, message in self.sent]
        self.assertEqual(len(keys), len(set(keys)))

    def test_never_more_than_four_messages_per_event_and_hour(self):
        by_event = {}
        for when, message in self.sent:
            by_event.setdefault(message.key.split(":")[0], []).append(when)
        for times in by_event.values():
            for index, start in enumerate(times):
                window = [t for t in times[index:] if t - start < timedelta(hours=1)]
                self.assertLessEqual(len(window), 4)


class Archive(unittest.TestCase):
    def test_reported_events_go_to_history_and_others_are_dropped(self):
        engine = Engine(make_cfg(), {})

        def script(minute, now):
            if minute <= 60:
                return [media("CU", 0.5, at(-40), now), media("AT", 0.004, at(-40), now)]
            if minute == 65:
                return [media("CU", None, at(-40), now, active=False), media("AT", None, at(-40), now, active=False)]
            return []

        sent = play(engine, script, 60 * 50, step=5)
        self.assertEqual(len(sent), 1)
        self.assertEqual(engine.state["events"], {})
        self.assertEqual(len(engine.state["history"]), 1)
        row = engine.state["history"][0]
        self.assertEqual((row["areas"], row["class"], row["media_only"]), (["CU"], "Blackout", True))
        self.assertGreater(parse_ts(row["ended_at"]), parse_ts(row["started_at"]))


if __name__ == "__main__":
    unittest.main()
