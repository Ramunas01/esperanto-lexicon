#!/usr/bin/env python3
"""Build Lithuanian concept_lang entries by cross-referencing English entries.

Sources:
  B — Hardcoded list of ~200 most common Lithuanian words for validation
  C — Hardcoded EN→LT translation table (~500 pairs, POS-aware for homographs)

Algorithm:
  For each English concept_lang entry (concept_id, word, pos, cefr_level, tier):
    1. Try POS-aware lookup: (word, pos) → LT form
    2. Fallback: word → LT form (generic mapping)
    3. If found and no LT entry already exists for this concept_id: insert

Usage:
    python3 src/lexicon/build_lt_lexicon.py \\
        --db data/lexicon_db/lexicon_v2.db [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Source B — common Lithuanian words (validation set)
# ---------------------------------------------------------------------------

_LT_COMMON_WORDS: set[str] = {
    # Pronouns
    "aš", "tu", "jis", "ji", "mes", "jūs", "jie", "jos",
    "mano", "tavo", "jo", "jos", "mūsų", "jūsų", "jų",
    "šis", "ši", "tas", "ta", "šie", "šios", "tie", "tos",
    "kas", "kuris", "kuri", "koks", "kiek",
    # Common verbs (infinitive)
    "būti", "turėti", "galėti", "eiti", "matyti", "žinoti",
    "sakyti", "norėti", "duoti", "imti", "daryti", "gauti",
    "ateiti", "pasakyti", "klausti", "dirbti", "naudoti",
    "rasti", "tikėti", "jausti", "bandyti", "atrodyti",
    "girdėti", "bėgti", "žaisti", "gyventi", "tapti",
    "rodyti", "laikyti", "pradėti", "kalbėti", "rašyti",
    "mylėti", "pirkti", "laukti", "grįžti", "mokėti",
    "reikėti", "leisti", "valgyti", "gerti", "miegoti",
    "skaityti", "suprasti", "padėti", "atnešti", "sekti",
    "nerti", "statyti", "likti", "kristi", "mirti",
    # Common nouns (nominative singular)
    "žmogus", "asmuo", "vaikas", "vyras", "moteris",
    "diena", "metai", "laikas", "gyvenimas", "pasaulis",
    "šalis", "mokykla", "šeima", "namai", "namas",
    "vanduo", "vieta", "miestas", "gatvė", "kelias",
    "knyga", "maistas", "pinigai", "kambarys", "naktis",
    "rytas", "savaitė", "mėnuo", "valanda", "skaičius",
    "vardas", "žodis", "klausimas", "atsakymas", "problema",
    "darbas", "ranka", "akis", "veidas", "galva", "koja",
    "širdis", "kūnas", "protas", "šviesa", "garsas", "oras",
    "ugnis", "žemė", "medis", "gyvūnas", "saulė", "mėnulis",
    "dangus", "lietus", "sniegas", "vasara", "žiema",
    "pavasaris", "ruduo", "vakaras", "durys", "langas",
    "stalas", "kėdė", "lova", "spalva", "kalba",
    # Common adjectives (nominative masculine singular)
    "geras", "blogas", "didelis", "mažas", "ilgas", "trumpas",
    "senas", "naujas", "jaunas", "aukštas", "žemas", "svarbus",
    "tikras", "teisingas", "gražus", "laimingas", "greitas",
    "lėtas", "stiprus", "silpnas", "lengvas", "sunkus",
    "karštas", "šaltas", "šiltas", "baltas", "juodas",
    "raudonas", "mėlynas", "žalias", "geltonas", "pirmasis",
    "paskutinis", "pilnas", "tuščias", "laisvas", "tikras",
    # Common adverbs
    "labai", "jau", "dar", "taip", "ne", "čia", "ten",
    "kaip", "kada", "kur", "dabar", "tada", "vėl",
    "niekada", "visada", "dažnai", "kartais", "paprastai",
    "daugiau", "mažiau", "gerai", "tik", "net", "vis",
    "taip pat", "jei", "nes", "nors",
    # Conjunctions and particles
    "ir", "bet", "ar", "arba", "kad", "nes", "jei", "nors",
    "tik", "net", "jau", "vis", "tai", "bei",
}

# ---------------------------------------------------------------------------
# Source C — EN→LT translation table (POS-aware for homographs)
# ---------------------------------------------------------------------------

# Checked first: (english_word, POS_tag) → lithuanian_base_form
_EN_TO_LT_BY_POS: dict[tuple[str, str], str] = {
    # Verbs vs nouns
    ("work", "VERB"): "dirbti", ("work", "NOUN"): "darbas",
    ("work", "SCONJ"): "dirbti",
    ("light", "NOUN"): "šviesa", ("light", "ADJ"): "lengvas",
    ("light", "VERB"): "apšviesti",
    ("run", "VERB"): "bėgti", ("run", "NOUN"): "bėgimas",
    ("play", "VERB"): "žaisti", ("play", "NOUN"): "žaidimas",
    ("love", "VERB"): "mylėti", ("love", "NOUN"): "meilė",
    ("help", "VERB"): "padėti", ("help", "NOUN"): "pagalba",
    ("change", "VERB"): "keisti", ("change", "NOUN"): "pokytis",
    ("place", "VERB"): "padėti", ("place", "NOUN"): "vieta",
    ("start", "VERB"): "pradėti", ("start", "NOUN"): "pradžia",
    ("stop", "VERB"): "sustoti", ("stop", "NOUN"): "sustojimas",
    ("show", "VERB"): "rodyti", ("show", "NOUN"): "paroda",
    ("answer", "VERB"): "atsakyti", ("answer", "NOUN"): "atsakymas",
    ("question", "NOUN"): "klausimas", ("question", "VERB"): "abejoti",
    ("result", "NOUN"): "rezultatas", ("result", "VERB"): "atsirasti",
    ("walk", "VERB"): "vaikščioti", ("walk", "NOUN"): "pasivaikščiojimas",
    ("call", "VERB"): "skambinti", ("call", "NOUN"): "skambutis",
    ("talk", "VERB"): "kalbėti", ("talk", "NOUN"): "pokalbis",
    ("back", "NOUN"): "nugara", ("back", "ADV"): "atgal",
    ("back", "ADJ"): "galinis", ("back", "VERB"): "remti",
    ("right", "ADJ"): "teisingas", ("right", "NOUN"): "teisė",
    ("right", "ADV"): "teisingai",
    ("round", "ADJ"): "apvalus", ("round", "NOUN"): "ratas",
    ("set", "VERB"): "nustatyti", ("set", "NOUN"): "rinkinys",
    ("set", "ADJ"): "nustatytas",
    ("kind", "NOUN"): "rūšis", ("kind", "ADJ"): "malonus",
    ("fast", "ADJ"): "greitas", ("fast", "ADV"): "greitai",
    ("hard", "ADJ"): "kietas", ("hard", "ADV"): "sunkiai",
    ("late", "ADJ"): "vėlyvas", ("late", "ADV"): "vėlai",
    ("early", "ADJ"): "ankstus", ("early", "ADV"): "anksti",
    ("free", "ADJ"): "laisvas", ("free", "VERB"): "išlaisvinti",
    ("open", "ADJ"): "atviras", ("open", "VERB"): "atidaryti",
    ("open", "NOUN"): "atvirumas",
    ("close", "VERB"): "uždaryti", ("close", "ADJ"): "artimas",
    ("mean", "VERB"): "reikšti", ("mean", "ADJ"): "vidutinis",
    ("left", "ADJ"): "kairys", ("left", "NOUN"): "kairė",
    ("past", "NOUN"): "praeitis", ("past", "ADJ"): "praėjęs",
    ("past", "ADP"): "pro",
    ("full", "ADJ"): "pilnas", ("full", "ADV"): "pilnai",
    ("live", "VERB"): "gyventi", ("live", "ADJ"): "tiesioginis",
    ("still", "ADV"): "dar", ("still", "ADJ"): "ramus",
    ("well", "ADV"): "gerai", ("well", "NOUN"): "šulinys",
    ("fine", "ADJ"): "puikus", ("fine", "NOUN"): "bauda",
    ("fair", "ADJ"): "teisingas", ("fair", "NOUN"): "mugė",
    ("lead", "VERB"): "vadovauti", ("lead", "NOUN"): "vadovavimas",
    ("match", "VERB"): "atitikti", ("match", "NOUN"): "rungtynės",
    ("watch", "VERB"): "stebėti", ("watch", "NOUN"): "laikrodis",
    ("order", "VERB"): "įsakyti", ("order", "NOUN"): "tvarka",
    ("address", "VERB"): "kreiptis", ("address", "NOUN"): "adresas",
    ("book", "VERB"): "rezervuoti", ("book", "NOUN"): "knyga",
    ("note", "VERB"): "pažymėti", ("note", "NOUN"): "pastaba",
    ("record", "VERB"): "įrašyti", ("record", "NOUN"): "įrašas",
    ("clear", "ADJ"): "aiškus", ("clear", "VERB"): "išvalyti",
    ("direct", "ADJ"): "tiesioginis", ("direct", "VERB"): "nukreipti",
    ("sound", "NOUN"): "garsas", ("sound", "VERB"): "skambėti",
    ("sound", "ADJ"): "sveikas",
    ("face", "NOUN"): "veidas", ("face", "VERB"): "susidurti",
    ("name", "NOUN"): "vardas", ("name", "VERB"): "pavadinti",
    ("hand", "NOUN"): "ranka", ("hand", "VERB"): "paduoti",
    ("air", "NOUN"): "oras", ("air", "VERB"): "vėdinti",
    ("care", "NOUN"): "rūpinimasis", ("care", "VERB"): "rūpintis",
    ("drive", "NOUN"): "kelionė", ("drive", "VERB"): "vairuoti",
    ("fall", "NOUN"): "kritimas", ("fall", "VERB"): "kristi",
    ("move", "NOUN"): "judėjimas", ("move", "VERB"): "judėti",
    ("break", "NOUN"): "pertrauka", ("break", "VERB"): "laužyti",
    ("plan", "NOUN"): "planas", ("plan", "VERB"): "planuoti",
    ("cut", "NOUN"): "pjūvis", ("cut", "VERB"): "pjauti",
    ("turn", "NOUN"): "posūkis", ("turn", "VERB"): "sukti",
    ("rise", "NOUN"): "kilimas", ("rise", "VERB"): "kilti",
    ("report", "NOUN"): "ataskaita", ("report", "VERB"): "pranešti",
    ("count", "NOUN"): "skaičiavimas", ("count", "VERB"): "skaičiuoti",
    ("study", "NOUN"): "tyrimas", ("study", "VERB"): "studijuoti",
    ("need", "NOUN"): "poreikis", ("need", "VERB"): "reikėti",
    ("wait", "NOUN"): "laukimas", ("wait", "VERB"): "laukti",
    ("control", "NOUN"): "kontrolė", ("control", "VERB"): "kontroliuoti",
    ("figure", "NOUN"): "skaičius", ("figure", "VERB"): "rodyti",
    ("mind", "NOUN"): "protas", ("mind", "VERB"): "prieštarauti",
    ("act", "NOUN"): "veiksmas", ("act", "VERB"): "veikti",
    ("deal", "NOUN"): "sandoris", ("deal", "VERB"): "spręsti",
    ("use", "NOUN"): "naudojimas", ("use", "VERB"): "naudoti",
    ("try", "NOUN"): "bandymas", ("try", "VERB"): "bandyti",
    ("end", "NOUN"): "galas", ("end", "VERB"): "baigti",
    ("rest", "NOUN"): "poilsis", ("rest", "VERB"): "ilsėtis",
    ("hit", "NOUN"): "smūgis", ("hit", "VERB"): "smogti",
    ("hold", "NOUN"): "laikymas", ("hold", "VERB"): "laikyti",
    ("look", "NOUN"): "žvilgsnis", ("look", "VERB"): "žiūrėti",
    ("form", "NOUN"): "forma", ("form", "VERB"): "formuoti",
    ("interest", "NOUN"): "palūkanos", ("interest", "VERB"): "dominti",
    ("store", "NOUN"): "parduotuvė", ("store", "VERB"): "laikyti",
    ("cover", "NOUN"): "viršelis", ("cover", "VERB"): "dengti",
    ("drink", "NOUN"): "gėrimas", ("drink", "VERB"): "gerti",
    ("plant", "NOUN"): "augalas", ("plant", "VERB"): "auginti",
    ("model", "NOUN"): "modelis", ("model", "VERB"): "modeliuoti",
    ("stage", "NOUN"): "etapas", ("stage", "VERB"): "organizuoti",
    ("test", "NOUN"): "testas", ("test", "VERB"): "testuoti",
    ("wish", "NOUN"): "noras", ("wish", "VERB"): "norėti",
    ("will", "NOUN"): "valia", ("will", "AUX"): "norėti",
    ("might", "NOUN"): "galybė", ("might", "AUX"): "galėti",
    ("pass", "NOUN"): "leidimas", ("pass", "VERB"): "praeiti",
    ("press", "NOUN"): "spauda", ("press", "VERB"): "spausti",
    ("last", "ADJ"): "paskutinis", ("last", "VERB"): "tęstis",
    ("last", "ADV"): "paskutinį kartą",
    ("own", "ADJ"): "savas", ("own", "VERB"): "turėti",
    ("spring", "NOUN"): "pavasaris", ("spring", "VERB"): "šokti",
    ("park", "NOUN"): "parkas", ("park", "VERB"): "statyti",
    ("charge", "NOUN"): "mokestis", ("charge", "VERB"): "apmokestinti",
    ("state", "NOUN"): "valstybė", ("state", "VERB"): "teigti",
    ("course", "NOUN"): "kursas", ("course", "ADV"): "žinoma",
    ("present", "ADJ"): "dabartinis", ("present", "NOUN"): "dovana",
    ("present", "VERB"): "pristatyti",
    ("type", "NOUN"): "tipas", ("type", "VERB"): "rašyti",
    ("love", "VERB"): "mylėti", ("love", "NOUN"): "meilė",
    ("rule", "NOUN"): "taisyklė", ("rule", "VERB"): "valdyti",
    ("process", "NOUN"): "procesas", ("process", "VERB"): "apdoroti",
    ("return", "NOUN"): "grąžinimas", ("return", "VERB"): "grįžti",
    ("support", "NOUN"): "parama", ("support", "VERB"): "remti",
    ("increase", "NOUN"): "padidėjimas", ("increase", "VERB"): "didinti",
    ("place", "NOUN"): "vieta", ("place", "VERB"): "padėti",
    ("program", "NOUN"): "programa", ("program", "VERB"): "programuoti",
    ("train", "NOUN"): "traukinys", ("train", "VERB"): "treniruoti",
    ("work", "VERB"): "dirbti", ("work", "NOUN"): "darbas",
}

# Generic fallback: english_word → most common lithuanian equivalent
_EN_TO_LT: dict[str, str] = {
    # --- PRONOUNS & DETERMINERS ---
    "i": "aš", "you": "tu", "he": "jis", "she": "ji",
    "we": "mes", "they": "jie", "it": "tai",
    "me": "manęs", "him": "jo", "her": "jos",
    "us": "mūsų", "them": "jų",
    "my": "mano", "your": "tavo", "his": "jo",
    "their": "jų", "our": "mūsų", "its": "jo",
    "this": "šis", "that": "tas", "these": "šie", "those": "tie",
    "who": "kas", "what": "kas", "which": "kuris",
    "all": "visas", "some": "kai kurie", "many": "daug",
    "few": "keli", "any": "bet koks", "each": "kiekvienas",
    "both": "abu", "other": "kitas", "another": "kitas",
    "such": "toks", "same": "pats", "every": "kiekvienas",
    "either": "vienas ar kitas", "neither": "nė vienas",
    "one": "vienas", "no": "jokio",
    # --- COMMON VERBS ---
    "be": "būti", "have": "turėti", "do": "daryti",
    "say": "sakyti", "get": "gauti", "make": "daryti",
    "go": "eiti", "know": "žinoti", "take": "imti",
    "see": "matyti", "come": "ateiti", "think": "galvoti",
    "look": "žiūrėti", "want": "norėti", "give": "duoti",
    "use": "naudoti", "find": "rasti", "tell": "pasakyti",
    "ask": "klausti", "work": "dirbti", "seem": "atrodyti",
    "feel": "jausti", "try": "bandyti", "leave": "išeiti",
    "call": "skambinti", "need": "reikėti", "become": "tapti",
    "show": "rodyti", "hear": "girdėti", "play": "žaisti",
    "run": "bėgti", "move": "judėti", "live": "gyventi",
    "believe": "tikėti", "hold": "laikyti", "bring": "atnešti",
    "happen": "atsitikti", "write": "rašyti", "sit": "sėdėti",
    "stand": "stovėti", "lose": "prarasti", "pay": "mokėti",
    "meet": "susitikti", "continue": "tęsti", "learn": "mokytis",
    "change": "keisti", "lead": "vadovauti", "understand": "suprasti",
    "watch": "stebėti", "follow": "sekti", "stop": "sustoti",
    "create": "kurti", "speak": "kalbėti", "read": "skaityti",
    "spend": "leisti", "grow": "augti", "open": "atidaryti",
    "walk": "vaikščioti", "offer": "pasiūlyti", "remember": "prisiminti",
    "love": "mylėti", "consider": "svarstyti", "appear": "pasirodyti",
    "buy": "pirkti", "wait": "laukti", "die": "mirti",
    "send": "siųsti", "expect": "tikėtis", "build": "statyti",
    "stay": "likti", "fall": "kristi", "cut": "pjauti",
    "reach": "pasiekti", "raise": "kelti", "pass": "praeiti",
    "sell": "parduoti", "decide": "nuspręsti", "return": "grįžti",
    "explain": "aiškinti", "hope": "tikėtis", "develop": "plėtoti",
    "carry": "nešti", "break": "laužyti", "receive": "gauti",
    "agree": "sutikti", "support": "remti", "produce": "gaminti",
    "eat": "valgyti", "catch": "pagauti", "choose": "rinktis",
    "drive": "vairuoti", "fight": "kovoti", "throw": "mesti",
    "close": "uždaryti", "win": "laimėti", "sing": "dainuoti",
    "fly": "skristi", "help": "padėti", "start": "pradėti",
    "begin": "pradėti", "sleep": "miegoti", "drink": "gerti",
    "add": "pridėti", "reduce": "sumažinti", "allow": "leisti",
    "include": "įtraukti", "keep": "laikyti", "put": "dėti",
    "let": "leisti", "mean": "reikšti", "set": "nustatyti",
    "provide": "teikti", "serve": "tarnauti", "cover": "dengti",
    "draw": "piešti", "swim": "plaukti", "turn": "sukti",
    "depend": "priklausyti", "talk": "kalbėti", "count": "skaičiuoti",
    "accept": "priimti", "suggest": "pasiūlyti", "achieve": "pasiekti",
    "avoid": "vengti", "contain": "turėti", "describe": "apibūdinti",
    "determine": "nustatyti", "enter": "įeiti", "establish": "įsteigti",
    "increase": "padidinti", "involve": "įtraukti", "obtain": "gauti",
    "perform": "atlikti", "prepare": "ruošti", "present": "pristatyti",
    "prevent": "užkirsti", "remain": "likti", "require": "reikalauti",
    "respond": "atsakyti", "share": "dalintis", "apply": "taikyti",
    "exist": "egzistuoti", "enable": "leisti", "represent": "atstovauti",
    "refer": "nurodyti", "discuss": "aptarti", "identify": "nustatyti",
    "ensure": "užtikrinti", "manage": "valdyti", "measure": "matuoti",
    "improve": "gerinti", "reduce": "sumažinti", "indicate": "rodyti",
    "maintain": "palaikyti", "compare": "lyginti", "introduce": "pristatyti",
    "focus": "sutelkti", "combine": "derinti", "create": "kurti",
    "define": "apibrėžti", "access": "pasiekti", "affect": "paveikti",
    "assume": "manyti", "calculate": "skaičiuoti", "collect": "rinkti",
    "communicate": "bendrauti", "connect": "sujungti", "contribute": "prisidėti",
    "design": "projektuoti", "discuss": "aptarti", "employ": "dirbti",
    "evaluate": "įvertinti", "examine": "išnagrinėti", "generate": "generuoti",
    "identify": "nustatyti", "implement": "įgyvendinti", "improve": "gerinti",
    "include": "įtraukti", "indicate": "rodyti", "influence": "daryti įtaką",
    "investigate": "tyrinėti", "involve": "įtraukti", "mention": "paminėti",
    "observe": "stebėti", "obtain": "gauti", "occur": "vykti",
    "operate": "valdyti", "organize": "organizuoti", "participate": "dalyvauti",
    "produce": "gaminti", "promote": "skatinti", "protect": "apsaugoti",
    "publish": "skelbti", "recognize": "atpažinti", "reduce": "sumažinti",
    "report": "pranešti", "represent": "atstovauti", "require": "reikalauti",
    "respond": "atsakyti", "select": "pasirinkti", "share": "dalintis",
    "support": "remti", "treat": "elgtis", "understand": "suprasti",
    # --- NOUNS ---
    "person": "asmuo", "people": "žmonės", "man": "vyras",
    "woman": "moteris", "child": "vaikas", "boy": "berniukas",
    "girl": "mergaitė", "baby": "kūdikis", "friend": "draugas",
    "family": "šeima", "parent": "tėvai", "father": "tėvas",
    "mother": "mama", "son": "sūnus", "daughter": "dukra",
    "brother": "brolis", "sister": "sesuo", "husband": "vyras",
    "wife": "žmona", "year": "metai", "day": "diena",
    "time": "laikas", "life": "gyvenimas", "world": "pasaulis",
    "country": "šalis", "school": "mokykla", "government": "vyriausybė",
    "house": "namas", "water": "vanduo", "place": "vieta",
    "home": "namai", "city": "miestas", "street": "gatvė",
    "car": "automobilis", "book": "knyga", "food": "maistas",
    "money": "pinigai", "road": "kelias", "room": "kambarys",
    "night": "naktis", "morning": "rytas", "week": "savaitė",
    "month": "mėnuo", "hour": "valanda", "minute": "minutė",
    "number": "skaičius", "name": "vardas", "word": "žodis",
    "problem": "problema", "idea": "idėja", "fact": "faktas",
    "way": "būdas", "work": "darbas", "job": "darbas",
    "hand": "ranka", "eye": "akis", "face": "veidas",
    "head": "galva", "leg": "koja", "heart": "širdis",
    "body": "kūnas", "mind": "protas", "letter": "laiškas",
    "color": "spalva", "colour": "spalva", "light": "šviesa",
    "sound": "garsas", "air": "oras", "fire": "ugnis",
    "earth": "žemė", "tree": "medis", "plant": "augalas",
    "animal": "gyvūnas", "dog": "šuo", "cat": "katė",
    "horse": "arklys", "bird": "paukštis", "fish": "žuvis",
    "town": "miestelis", "village": "kaimas", "river": "upė",
    "lake": "ežeras", "sea": "jūra", "mountain": "kalnas",
    "land": "žemė", "sun": "saulė", "moon": "mėnulis",
    "star": "žvaigždė", "sky": "dangus", "cloud": "debesis",
    "rain": "lietus", "snow": "sniegas", "wind": "vėjas",
    "weather": "oras", "summer": "vasara", "winter": "žiema",
    "spring": "pavasaris", "autumn": "ruduo", "evening": "vakaras",
    "afternoon": "popietė", "door": "durys", "window": "langas",
    "floor": "grindys", "wall": "siena", "table": "stalas",
    "chair": "kėdė", "bed": "lova", "kitchen": "virtuvė",
    "garden": "sodas", "park": "parkas", "hospital": "ligoninė",
    "shop": "parduotuvė", "bank": "bankas", "market": "rinka",
    "office": "biuras", "university": "universitetas",
    "church": "bažnyčia", "hotel": "viešbutis",
    "restaurant": "restoranas", "airport": "oro uostas",
    "station": "stotis", "computer": "kompiuteris",
    "phone": "telefonas", "television": "televizorius",
    "radio": "radijas", "newspaper": "laikraštis",
    "magazine": "žurnalas", "music": "muzika", "film": "filmas",
    "game": "žaidimas", "sport": "sportas", "team": "komanda",
    "player": "žaidėjas", "ball": "kamuolys", "arm": "ranka",
    "foot": "koja", "hair": "plaukai", "shoulder": "petys",
    "knee": "kelis", "mouth": "burna", "nose": "nosis",
    "ear": "ausis", "tooth": "dantis", "finger": "pirštas",
    "skin": "oda", "blood": "kraujas", "price": "kaina",
    "cost": "kaina", "tax": "mokestis", "income": "pajamos",
    "profit": "pelnas", "loss": "nuostolis", "benefit": "nauda",
    "value": "vertė", "service": "paslauga", "product": "produktas",
    "company": "įmonė", "business": "verslas", "industry": "pramonė",
    "economy": "ekonomika", "society": "visuomenė",
    "community": "bendruomenė", "group": "grupė",
    "organization": "organizacija", "organisation": "organizacija",
    "association": "asociacija", "meeting": "susirinkimas",
    "member": "narys", "leader": "vadovas", "manager": "vadybininkas",
    "director": "direktorius", "minister": "ministras",
    "president": "prezidentas", "law": "įstatymas",
    "rule": "taisyklė", "right": "teisė", "duty": "pareiga",
    "responsibility": "atsakomybė", "agreement": "susitarimas",
    "contract": "sutartis", "decision": "sprendimas",
    "information": "informacija", "data": "duomenys",
    "report": "ataskaita", "question": "klausimas",
    "answer": "atsakymas", "result": "rezultatas",
    "effect": "poveikis", "reason": "priežastis",
    "example": "pavyzdys", "case": "atvejis",
    "situation": "situacija", "condition": "sąlyga",
    "process": "procesas", "method": "metodas",
    "system": "sistema", "area": "sritis", "field": "sritis",
    "level": "lygis", "type": "tipas", "kind": "rūšis",
    "part": "dalis", "point": "taškas", "line": "linija",
    "side": "pusė", "end": "galas", "beginning": "pradžia",
    "center": "centras", "centre": "centras", "top": "viršus",
    "bottom": "apačia", "form": "forma", "image": "vaizdas",
    "picture": "nuotrauka", "language": "kalba", "culture": "kultūra",
    "art": "menas", "science": "mokslas", "technology": "technologija",
    "health": "sveikata", "education": "švietimas",
    "environment": "aplinka", "nature": "gamta", "power": "galia",
    "force": "jėga", "energy": "energija", "space": "erdvė",
    "size": "dydis", "speed": "greitis", "quality": "kokybė",
    "quantity": "kiekis", "amount": "suma", "age": "amžius",
    "century": "amžius", "decade": "dešimtmetis",
    "period": "laikotarpis", "moment": "momentas",
    "future": "ateitis", "past": "praeitis", "present": "dabartis",
    "history": "istorija", "event": "įvykis",
    "experience": "patirtis", "knowledge": "žinios",
    "truth": "tiesa", "peace": "taika", "war": "karas",
    "state": "valstybė", "nation": "tauta", "region": "regionas",
    "address": "adresas", "action": "veiksmas", "activity": "veikla",
    "actor": "aktorius", "actress": "aktorė", "adult": "suaugęs",
    "advice": "patarimas", "account": "sąskaita", "age": "amžius",
    "interview": "interviu", "attitude": "požiūris",
    "attention": "dėmesys", "audience": "auditorija",
    "authority": "valdžia", "award": "apdovanojimas",
    "behavior": "elgesys", "behaviour": "elgesys",
    "belief": "tikėjimas", "bill": "sąskaita",
    "birth": "gimimas", "campaign": "kampanija",
    "cause": "priežastis", "chance": "galimybė",
    "character": "charakteris", "choice": "pasirinkimas",
    "citizen": "pilietis", "class": "klasė",
    "climate": "klimatas", "code": "kodas",
    "committee": "komitetas", "communication": "komunikacija",
    "competition": "konkurencija", "concern": "rūpestis",
    "council": "taryba", "crisis": "krizė",
    "culture": "kultūra", "currency": "valiuta",
    "death": "mirtis", "debate": "debatai",
    "democracy": "demokratija", "development": "plėtra",
    "difference": "skirtumas", "difficulty": "sunkumas",
    "discussion": "diskusija", "document": "dokumentas",
    "economy": "ekonomika", "election": "rinkimai",
    "employee": "darbuotojas", "employer": "darbdavys",
    "evidence": "įrodymai", "examination": "egzaminas",
    "example": "pavyzdys", "exercise": "pratimas",
    "expense": "išlaidos", "explanation": "paaiškinimas",
    "failure": "nesėkmė", "freedom": "laisvė",
    "function": "funkcija", "future": "ateitis",
    "growth": "augimas", "guide": "vadovas",
    "impact": "poveikis", "importance": "svarba",
    "individual": "asmuo", "institution": "institucija",
    "investment": "investicija", "issue": "klausimas",
    "leadership": "vadovavimas", "management": "valdymas",
    "media": "žiniasklaida", "memory": "atmintis",
    "message": "žinutė", "model": "modelis",
    "movement": "judėjimas", "network": "tinklas",
    "opinion": "nuomonė", "opportunity": "galimybė",
    "option": "variantas", "organization": "organizacija",
    "pattern": "modelis", "population": "gyventojai",
    "position": "pozicija", "possibility": "galimybė",
    "practice": "praktika", "pressure": "spaudimas",
    "project": "projektas", "property": "turtas",
    "purpose": "tikslas", "question": "klausimas",
    "relationship": "ryšys", "research": "tyrimas",
    "resource": "išteklius", "response": "atsakas",
    "role": "vaidmuo", "sale": "pardavimas",
    "security": "saugumas", "series": "serija",
    "solution": "sprendimas", "source": "šaltinis",
    "standard": "standartas", "statement": "pareiškimas",
    "strategy": "strategija", "structure": "struktūra",
    "subject": "tema", "success": "sėkmė",
    "task": "užduotis", "theory": "teorija",
    "thought": "mintis", "topic": "tema",
    "tradition": "tradicija", "understanding": "supratimas",
    "unit": "vienetas", "version": "versija",
    "view": "požiūris", "vision": "vizija",
    "voice": "balsas", "volume": "tomas",
    "weight": "svoris", "welfare": "gerovė",
    # --- ADJECTIVES ---
    "good": "geras", "bad": "blogas", "big": "didelis",
    "large": "didelis", "small": "mažas", "little": "mažas",
    "long": "ilgas", "short": "trumpas", "old": "senas",
    "new": "naujas", "young": "jaunas", "high": "aukštas",
    "low": "žemas", "important": "svarbus", "possible": "galimas",
    "real": "tikras", "true": "teisingas", "beautiful": "gražus",
    "happy": "laimingas", "sad": "liūdnas", "fast": "greitas",
    "quick": "greitas", "slow": "lėtas", "strong": "stiprus",
    "weak": "silpnas", "easy": "lengvas", "difficult": "sunkus",
    "hard": "sunkus", "soft": "minkštas", "hot": "karštas",
    "cold": "šaltas", "warm": "šiltas", "white": "baltas",
    "black": "juodas", "red": "raudonas", "blue": "mėlynas",
    "green": "žalias", "yellow": "geltonas", "brown": "rudas",
    "first": "pirmas", "last": "paskutinis", "next": "kitas",
    "different": "skirtingas", "free": "laisvas", "ready": "pasiruošęs",
    "sure": "tikras", "full": "pilnas", "empty": "tuščias",
    "dark": "tamsus", "clear": "aiškus", "deep": "gilus",
    "early": "ankstus", "late": "vėlyvas", "right": "teisingas",
    "wrong": "neteisingas", "open": "atviras", "closed": "uždarytas",
    "wide": "platus", "narrow": "siauras", "heavy": "sunkus",
    "rich": "turtingas", "poor": "skurdus", "safe": "saugus",
    "dangerous": "pavojingas", "common": "įprastas",
    "special": "ypatingas", "natural": "natūralus",
    "human": "žmogiškas", "social": "socialinis",
    "political": "politinis", "economic": "ekonominis",
    "national": "nacionalinis", "international": "tarptautinis",
    "local": "vietinis", "public": "viešas", "private": "privatus",
    "personal": "asmeninis", "general": "bendras",
    "specific": "konkretus", "main": "pagrindinis",
    "basic": "pagrindinis", "simple": "paprastas",
    "complex": "sudėtingas", "normal": "įprastas", "great": "puikus",
    "perfect": "tobulas", "certain": "tikras", "various": "įvairūs",
    "whole": "visas", "direct": "tiesioginis", "similar": "panašus",
    "necessary": "būtinas", "available": "prieinamas",
    "current": "dabartinis", "physical": "fizinis",
    "final": "galutinis", "official": "oficialus", "legal": "teisinis",
    "annual": "metinis", "total": "bendras", "foreign": "užsienio",
    "additional": "papildomas", "major": "pagrindinis",
    "significant": "reikšmingas", "original": "originalus",
    "traditional": "tradicinis", "modern": "modernus",
    "practical": "praktinis", "positive": "teigiamas",
    "negative": "neigiamas", "active": "aktyvus",
    "effective": "veiksmingas", "successful": "sėkmingas",
    "popular": "populiarus", "comfortable": "patogus",
    "clean": "švarus", "dirty": "nešvarus", "fresh": "šviežias",
    "dry": "sausas", "wet": "šlapias", "loud": "garsus",
    "quiet": "tylus", "ugly": "bjaurus", "clever": "protingas",
    "stupid": "kvailas", "kind": "malonus", "honest": "sąžiningas",
    "brave": "drąsus", "lazy": "tingus", "busy": "užsiėmęs",
    "tired": "pavargęs", "hungry": "alkanas", "sick": "sergantis",
    "healthy": "sveikas", "alive": "gyvas", "dead": "miręs",
    "amazing": "nuostabus", "afraid": "bijantis",
    "angry": "piktas", "careful": "atsargus",
    "careful": "atsargus", "cheap": "pigus", "expensive": "brangus",
    "correct": "teisingas", "familiar": "pažįstamas",
    "interesting": "įdomus", "strange": "keistas",
    "funny": "juokingas", "serious": "rimtas",
    "important": "svarbus", "ancient": "senovinis",
    "average": "vidutinis", "bright": "ryškus",
    "certain": "tikras", "complete": "baigtas",
    "considerable": "nemažas", "constant": "pastovus",
    "correct": "teisingas", "critical": "kritinis",
    "cultural": "kultūrinis", "democratic": "demokratinis",
    "detailed": "išsamus", "digital": "skaitmeninis",
    "entire": "visas", "essential": "esminis",
    "exact": "tikslus", "excellent": "puikus",
    "existing": "esamas", "extreme": "ekstremalus",
    "familiar": "pažįstamas", "formal": "oficialus",
    "former": "buvęs", "global": "globalus",
    "immediate": "nedelsiant", "individual": "asmeninis",
    "industrial": "pramoninis", "initial": "pradinis",
    "inner": "vidinis", "internal": "vidinis",
    "joint": "bendras", "key": "svarbiausias",
    "known": "žinomas", "likely": "tikėtinas",
    "major": "pagrindinis", "mental": "psichinis",
    "military": "karinis", "multiple": "daugybinis",
    "mutual": "abipusis", "obvious": "akivaizdus",
    "particular": "konkretus", "permanent": "nuolatinis",
    "physical": "fizinis", "precise": "tikslus",
    "primary": "pirminis", "proper": "tinkamas",
    "reasonable": "pagrįstas", "relevant": "aktualus",
    "responsible": "atsakingas", "scientific": "mokslinis",
    "secondary": "antrinis", "separate": "atskiras",
    "serious": "rimtas", "sharp": "aštrus",
    "single": "vienas", "slight": "nežymus",
    "solid": "tvirtas", "suitable": "tinkamas",
    "theoretical": "teorinis", "typical": "tipiškas",
    "uncertain": "neaiškus", "unique": "unikalus",
    "useful": "naudingas", "valid": "galiojantis",
    "visual": "vaizdinis", "vital": "gyvybiškai svarbus",
    "wooden": "medinis",
    # --- ADVERBS ---
    "very": "labai", "much": "daug", "more": "daugiau",
    "less": "mažiau", "most": "daugiausiai", "also": "taip pat",
    "too": "taip pat", "only": "tik", "just": "tik",
    "still": "dar", "already": "jau", "again": "vėl",
    "never": "niekada", "always": "visada", "often": "dažnai",
    "sometimes": "kartais", "usually": "paprastai",
    "now": "dabar", "then": "tada", "here": "čia",
    "there": "ten", "where": "kur", "when": "kada",
    "how": "kaip", "why": "kodėl", "maybe": "galbūt",
    "perhaps": "galbūt", "yes": "taip", "not": "ne",
    "together": "kartu", "alone": "vienas", "enough": "pakankamai",
    "almost": "beveik", "quite": "gana", "rather": "gana",
    "so": "taip", "well": "gerai", "slowly": "lėtai",
    "easily": "lengvai", "clearly": "aiškiai", "simply": "paprastai",
    "directly": "tiesiogiai", "finally": "galutinai",
    "recently": "neseniai", "soon": "netrukus", "late": "vėlai",
    "early": "anksti", "today": "šiandien", "yesterday": "vakar",
    "tomorrow": "rytoj", "everywhere": "visur", "anywhere": "bet kur",
    "somewhere": "kažkur", "nowhere": "niekur",
    "away": "tolyn", "up": "aukštyn", "down": "žemyn",
    "forward": "pirmyn", "inside": "viduje", "outside": "lauke",
    "above": "viršuje", "below": "žemiau", "across": "per",
    "ahead": "priekyje", "apart": "atskirai", "around": "aplink",
    "ago": "prieš", "already": "jau", "anyway": "bet kokiu atveju",
    "approximately": "maždaug", "certainly": "tikrai",
    "completely": "visiškai", "currently": "šiuo metu",
    "deeply": "giliai", "especially": "ypač",
    "eventually": "galų gale", "exactly": "tiksliai",
    "extremely": "itin", "frequently": "dažnai",
    "generally": "apskritai", "gradually": "palaipsniui",
    "greatly": "gerokai", "highly": "labai", "immediately": "nedelsiant",
    "indeed": "iš tiesų", "likely": "tikėtinai",
    "mainly": "daugiausia", "merely": "tik",
    "mostly": "daugiausia", "nearly": "beveik",
    "obviously": "akivaizdžiai", "often": "dažnai",
    "otherwise": "kitaip", "particularly": "ypač",
    "perfectly": "puikiai", "possibly": "galbūt",
    "precisely": "tiksliai", "previously": "anksčiau",
    "probably": "greičiausiai", "quickly": "greitai",
    "quite": "gana", "rapidly": "sparčiai",
    "really": "tikrai", "relatively": "palyginti",
    "roughly": "apytiksliai", "seriously": "rimtai",
    "significantly": "reikšmingai", "simply": "paprastai",
    "slightly": "šiek tiek", "specifically": "konkrečiai",
    "strongly": "stipriai", "suddenly": "staiga",
    "therefore": "todėl", "thus": "taigi",
    "typically": "paprastai", "ultimately": "galutinai",
    "usually": "paprastai", "widely": "plačiai",
    # --- PREPOSITIONS & CONJUNCTIONS ---
    "and": "ir", "but": "bet", "or": "arba",
    "if": "jei", "because": "nes", "although": "nors",
    "while": "kol", "since": "kadangi", "unless": "jei ne",
    "before": "prieš", "after": "po", "until": "iki",
    "about": "apie", "above": "virš", "against": "prieš",
    "among": "tarp", "around": "aplink", "at": "prie",
    "between": "tarp", "by": "prie", "during": "per",
    "except": "išskyrus", "for": "dėl", "from": "iš",
    "in": "viduje", "into": "į", "near": "netoli",
    "of": "iš", "on": "ant", "out": "iš",
    "over": "virš", "through": "per", "to": "į",
    "toward": "link", "towards": "link", "under": "po",
    "with": "su", "without": "be", "within": "viduje",
    "per": "per", "via": "per", "despite": "nepaisant",
    "however": "tačiau", "therefore": "todėl",
    "hence": "taigi", "moreover": "be to",
    "furthermore": "be to", "nevertheless": "nepaisant to",
    "whereas": "tuo tarpu", "whether": "ar",
    "than": "nei", "as": "kaip",
    "a": "vienas", "an": "vienas", "the": "tas",
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _lt_for(word: str, pos: str | None) -> str | None:
    """Return the best Lithuanian equivalent for an English word+POS pair."""
    if pos:
        lt = _EN_TO_LT_BY_POS.get((word.lower(), pos))
        if lt:
            return lt
    return _EN_TO_LT.get(word.lower())


def run(db_path: Path, dry_run: bool = False) -> None:
    """Insert LT concept_lang entries derived from existing EN entries."""
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    # Load all EN entries
    en_rows = conn.execute(
        "SELECT concept_id, word, pos, cefr_level, tier FROM concept_lang WHERE lang = 'en'"
    ).fetchall()

    # Load existing LT concept_ids to skip
    existing_lt_concepts: set[int] = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT concept_id FROM concept_lang WHERE lang = 'lt'"
        )
    }

    found = 0
    skipped = 0
    inserted = 0

    to_insert: list[tuple] = []

    for concept_id, en_word, pos, cefr_level, tier in en_rows:
        if concept_id in existing_lt_concepts:
            skipped += 1
            continue

        lt_word = _lt_for(en_word, pos)
        if lt_word is None:
            skipped += 1
            continue

        found += 1
        to_insert.append((concept_id, "lt", lt_word, pos, cefr_level, tier, "build_lt_lexicon.py"))
        # Mark as done so later EN entries for same concept don't double-insert
        existing_lt_concepts.add(concept_id)

    if not dry_run:
        conn.executemany(
            """
            INSERT OR IGNORE INTO concept_lang
                (concept_id, lang, word, pos, cefr_level, tier, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            to_insert,
        )
        conn.commit()
        inserted = len(to_insert)
    else:
        inserted = len(to_insert)
        print("(dry-run — no changes written)")
        for row in to_insert[:20]:
            print(f"  would insert: concept_id={row[0]} lt={row[2]!r} (en={_find_en(conn, row[0])!r})")
        if len(to_insert) > 20:
            print(f"  ... and {len(to_insert) - 20} more")

    conn.close()

    # Validation: how many LT words are in the common word set?
    lt_words = {row[2] for row in to_insert}
    validated = len(lt_words & _LT_COMMON_WORDS)

    print()
    print(f"Concepts with LT mapping found : {found}")
    print(f"Concepts skipped (no LT found) : {skipped}")
    print(f"New concept_lang rows inserted : {inserted}")
    print(f"LT words validated by Source B : {validated} / {len(lt_words)}")


def _find_en(conn: sqlite3.Connection, concept_id: int) -> str:
    row = conn.execute(
        "SELECT word FROM concept_lang WHERE concept_id = ? AND lang = 'en' LIMIT 1",
        (concept_id,),
    ).fetchone()
    return row[0] if row else "?"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build Lithuanian concept_lang entries from English→Lithuanian mappings."
    )
    parser.add_argument("--db", required=True, type=Path, help="Path to lexicon_v2.db")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be inserted without writing to the database",
    )
    args = parser.parse_args(argv)
    run(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
