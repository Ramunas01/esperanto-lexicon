"""Propose Esperanto equivalents for vocabulary rows that have none.

Reads data/lexicon_db/lexicon.db (v1), finds rows where esperanto_word IS NULL,
applies a hardcoded mapping and a root-similarity heuristic, and writes
candidates to data/lexicon_db/enrichment_candidates.jsonl for human review.

The DB is never modified by this script.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple

DB_PATH = Path(__file__).parents[2] / "data" / "lexicon_db" / "lexicon.db"
OUT_PATH = Path(__file__).parents[2] / "data" / "lexicon_db" / "enrichment_candidates.jsonl"


class EoProposal(NamedTuple):
    eo_word: str
    eo_root: str
    eo_ending: str
    eo_prefix: str
    eo_suffix: str
    eo_pos: str
    confidence: str  # 'high' | 'medium' | 'low'
    method: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Hardcoded mapping: (english_word, pos) -> EoProposal
# POS tags match spaCy UD labels used in v1: NOUN VERB ADJ ADV ADP DET
# PRON NUM CCONJ INTJ AUX UNKNOWN
# ---------------------------------------------------------------------------
_H = "high"
_M = "medium"
_L = "low"


def _n(w: str, r: str, e: str = "o", pre: str = "", suf: str = "", c: str = _H, note: str = "") -> EoProposal:
    return EoProposal(w, r, e, pre, suf, "NOUN", c, "hardcoded", note)


def _v(w: str, r: str, e: str = "i", pre: str = "", suf: str = "", c: str = _H, note: str = "") -> EoProposal:
    return EoProposal(w, r, e, pre, suf, "VERB", c, "hardcoded", note)


def _a(w: str, r: str, e: str = "a", pre: str = "", suf: str = "", c: str = _H, note: str = "") -> EoProposal:
    return EoProposal(w, r, e, pre, suf, "ADJ", c, "hardcoded", note)


def _r(w: str, r: str, e: str = "e", pre: str = "", suf: str = "", c: str = _H, note: str = "") -> EoProposal:
    return EoProposal(w, r, e, pre, suf, "ADV", c, "hardcoded", note)


def _i(w: str, r: str, e: str = "", pre: str = "", suf: str = "", c: str = _M, note: str = "") -> EoProposal:
    return EoProposal(w, r, e, pre, suf, "INTJ", c, "hardcoded", note)


MAPPING: dict[tuple[str, str], EoProposal | None] = {
    # DET / function words
    ("a", "DET"): None,  # Esperanto has no indefinite article
    ("last", "DET"): None,  # handled as ADJ sense below
    ("percent", "ADJ"): None,
    ("percent", "ADV"): None,
    ("second", "DET"): None,
    ("second", "NUM"): None,
    ("folk", "ADJ"): None,
    ("long-term", "ADV"): None,
    ("plus", "ADP"): None,
    ("plus", "CCONJ"): None,
    ("toward", "ADP"): None,  # 'al' but direction preposition; ambiguous
    ("don't", "AUX"): None,
    ("can", "AUX"): None,   # modal: 'povas'; no clean nominal form
    ("do", "AUX"): None,
    ("ought", "AUX"): None,
    ("these", "UNKNOWN"): None,
    ("those", "UNKNOWN"): None,
    # Nouns
    ("administration", "NOUN"): _n("administracio", "administraci"),
    ("agenda", "NOUN"): _n("agendo", "agend"),
    ("airline", "NOUN"): _n("flugkompanio", "flugkompani", pre="flug"),
    ("album", "NOUN"): _n("albumo", "album"),
    ("announcement", "NOUN"): _n("anonco", "anonc"),
    ("app", "NOUN"): _n("aplikaĵo", "aplik", suf="aĵ", c=_M, note="also 'appo' as internationalism"),
    ("architect", "NOUN"): _n("arkitekto", "arkitekt"),
    ("architecture", "NOUN"): _n("arkitekturo", "arkitektur"),
    ("assessment", "NOUN"): _n("taksado", "taks", suf="ad"),
    ("assignment", "NOUN"): _n("tasko", "task"),
    ("athlete", "NOUN"): _n("atleto", "atlet"),
    ("banana", "NOUN"): _n("banano", "banan"),
    ("baseball", "NOUN"): _n("basebalo", "basebal"),
    ("basketball", "NOUN"): _n("korbopilko", "korbopilk", pre="korbo", c=_M, note="also 'basketbalo'"),
    ("bean", "NOUN"): _n("fabo", "fab"),
    ("bee", "NOUN"): _n("abelo", "abel"),
    ("being", "NOUN"): _n("estaĵo", "est", suf="aĵ"),
    ("blog", "NOUN"): _n("blogo", "blog"),
    ("bond", "NOUN"): _n("ligilo", "ligil", suf="il", c=_M, note="chemical bond; financial bond = obligacio"),
    ("bride", "NOUN"): _n("novedzino", "novedz", suf="in"),
    ("cafe", "NOUN"): _n("kafejo", "kafej", suf="ej"),
    ("campus", "NOUN"): _n("kampuso", "kampus"),
    ("can", "NOUN"): _n("skatolo", "skatol"),
    ("cartoon", "NOUN"): _n("karikaturo", "karikatur", c=_M, note="political; animated = desegnofilmo"),
    ("celebrity", "NOUN"): _n("famo", "fam", c=_M, note="or 'celebrit-o' as internationalism"),
    ("center", "NOUN"): _n("centro", "centr"),
    ("champion", "NOUN"): _n("ĉampiono", "ĉampion"),
    ("chef", "NOUN"): _n("ĉefkuiristo", "ĉefkuirist", pre="ĉef"),
    ("childhood", "NOUN"): _n("infanaĝo", "infanaĝ", pre="infan"),
    ("clause", "NOUN"): _n("subfrazo", "subfraz", pre="sub", c=_M, note="grammatical; legal = klaŭzo"),
    ("clue", "NOUN"): _n("sugesto", "sugest", c=_M),
    ("color", "NOUN"): _n("koloro", "kolor"),
    ("competitor", "NOUN"): _n("konkuranto", "konkur", suf="ant"),
    ("component", "NOUN"): _n("komponanto", "kompon", suf="ant"),
    ("content", "NOUN"): _n("enhavo", "enhav", pre="en"),
    ("corn", "NOUN"): _n("maizo", "maiz"),
    ("costume", "NOUN"): _n("kostumo", "kostum"),
    ("creation", "NOUN"): _n("kreado", "kre", suf="ad"),
    ("crew", "NOUN"): _n("ekipo", "ekip", c=_M),
    ("critic", "NOUN"): _n("kritikisto", "kritik", suf="ist"),
    ("currency", "NOUN"): _n("valuto", "valut"),
    ("defense", "NOUN"): _n("defendo", "defend"),
    ("designer", "NOUN"): _n("dezajnisto", "dezajn", suf="ist"),
    ("dessert", "NOUN"): _n("deserto", "desert"),
    ("destination", "NOUN"): _n("celloko", "celllok", pre="cel", c=_M),
    ("detective", "NOUN"): _n("detektivo", "detektiv"),
    ("dialogue", "NOUN"): _n("dialogo", "dialog"),
    ("documentary", "NOUN"): _n("dokumentfilmo", "dokumentfilm", pre="dokument"),
    ("download", "NOUN"): _n("elŝuto", "elŝut", pre="el"),
    ("downtown", "NOUN"): _n("urbocentro", "urbocentr", pre="urbo"),
    ("earthquake", "NOUN"): _n("tertremo", "tertrem", pre="ter"),
    ("elephant", "NOUN"): _n("elefanto", "elefant"),
    ("episode", "NOUN"): _n("epizodo", "epizod"),
    ("exploration", "NOUN"): _n("esplorado", "esplor", suf="ad"),
    ("favor", "NOUN"): _n("favoro", "favor"),
    ("favorite", "NOUN"): _n("favorato", "favorat"),
    ("feedback", "NOUN"): _n("retroigo", "retro", suf="ig", c=_M, note="or 'retroago'"),
    ("fiction", "NOUN"): _n("fikcio", "fikci"),
    ("finding", "NOUN"): _n("trovaĵo", "trov", suf="aĵ", c=_M),
    ("fitness", "NOUN"): _n("kondicio", "kondici", c=_M),
    ("folk", "NOUN"): _n("popolo", "popol"),
    ("frequency", "NOUN"): _n("frekvenco", "frekvenc"),
    ("frog", "NOUN"): _n("rano", "ran"),
    ("funding", "NOUN"): _n("financado", "financ", suf="ad"),
    ("gallery", "NOUN"): _n("galerio", "galeri"),
    ("gang", "NOUN"): _n("bando", "band"),
    ("genre", "NOUN"): _n("ĝenro", "ĝenr"),
    ("ghost", "NOUN"): _n("fantomo", "fantom"),
    ("golf", "NOUN"): _n("golfo", "golf"),
    ("graduate", "NOUN"): _n("absolventino", "absolvent", suf="in", c=_M),
    ("gray", "NOUN"): _n("grizo", "griz"),
    ("guitar", "NOUN"): _n("gitaro", "gitar"),
    ("gym", "NOUN"): _n("gimnastikejo", "gimnastik", suf="ej"),
    ("headline", "NOUN"): _n("titolo", "titol"),
    ("helicopter", "NOUN"): _n("helikoptero", "helikopter"),
    ("hockey", "NOUN"): _n("hokeo", "hoke"),
    ("honor", "NOUN"): _n("honoro", "honor"),
    ("humor", "NOUN"): _n("humuro", "humur"),
    ("hurricane", "NOUN"): _n("uragano", "uragan"),
    ("illustration", "NOUN"): _n("ilustraĵo", "ilustr", suf="aĵ"),
    ("immigrant", "NOUN"): _n("enmigrantino", "enmigrant", pre="en", suf="in", c=_M),
    ("inquiry", "NOUN"): _n("enketo", "enket", pre="en"),
    ("insight", "NOUN"): _n("kompreno", "kompren", c=_M),
    ("instructor", "NOUN"): _n("instruisto", "instru", suf="ist"),
    ("jazz", "NOUN"): _n("jazo", "jaz"),
    ("jewelry", "NOUN"): _n("juvelaĵo", "juvela", suf="ĵ", c=_M),
    ("journal", "NOUN"): _n("ĵurnalo", "ĵurnal", c=_M, note="press journal; personal diary = taglibro"),
    ("judgment", "NOUN"): _n("juĝo", "juĝ"),
    ("kilometer", "NOUN"): _n("kilometro", "kilometr"),
    ("labor", "NOUN"): _n("laboreco", "labor", suf="ec", c=_M),
    ("laptop", "NOUN"): _n("laptopo", "laptop"),
    ("last", "NOUN"): _n("fino", "fin"),
    ("laughter", "NOUN"): _n("ridado", "rid", suf="ad"),
    ("lead", "NOUN"): _n("avantaĝo", "avantaĝ", c=_M, note="race lead; chemical lead = plumbo"),
    ("leadership", "NOUN"): _n("gvidado", "gvid", suf="ad"),
    ("learning", "NOUN"): _n("lernado", "lern", suf="ad"),
    ("leisure", "NOUN"): _n("libertempo", "libertemp", pre="liber"),
    ("lie", "NOUN"): _n("mensogo", "mensog"),
    ("lifestyle", "NOUN"): _n("vivmaniero", "vivmanier", pre="viv"),
    ("lion", "NOUN"): _n("leono", "leon"),
    ("listener", "NOUN"): _n("aŭskultanto", "aŭskult", suf="ant"),
    ("luxury", "NOUN"): _n("lukso", "luks"),
    ("math", "NOUN"): _n("matematiko", "matematik"),
    ("meter", "NOUN"): _n("metro", "metr"),
    ("minute", "NOUN"): _n("minuto", "minut"),
    ("mission", "NOUN"): _n("misio", "misi"),
    ("monkey", "NOUN"): _n("simio", "simi"),
    ("narrative", "NOUN"): _n("rakonto", "rakont"),
    ("native", "NOUN"): _n("indiĝeno", "indiĝen"),
    ("neighbor", "NOUN"): _n("najbaro", "najbar"),
    ("neighborhood", "NOUN"): _n("najbareco", "najbar", suf="ec"),
    ("nightmare", "NOUN"): _n("inkubo", "inkub"),
    ("notion", "NOUN"): _n("nocio", "noci"),
    ("obligation", "NOUN"): _n("devigo", "devig"),
    ("organizer", "NOUN"): _n("organizanto", "organiz", suf="ant"),
    ("outcome", "NOUN"): _n("rezulto", "rezult"),
    ("pace", "NOUN"): _n("paŝo", "paŝ"),
    ("pan", "NOUN"): _n("pato", "pat"),
    ("paragraph", "NOUN"): _n("paragrafo", "paragraf"),
    ("parking", "NOUN"): _n("parkumado", "parkum", suf="ad"),
    ("participant", "NOUN"): _n("partoprenanto", "partoprenan", pre="parto", suf="ant"),
    ("passion", "NOUN"): _n("pasio", "pasi"),
    ("percent", "NOUN"): _n("procento", "procent"),
    ("percentage", "NOUN"): _n("procento", "procent"),
    ("perspective", "NOUN"): _n("perspektivo", "perspektiv"),
    ("phenomenon", "NOUN"): _n("fenomeno", "fenomen"),
    ("plus", "NOUN"): _n("pluso", "plus"),
    ("poet", "NOUN"): _n("poeto", "poet"),
    ("policeman", "NOUN"): _n("policisto", "polici", suf="st", c=_M),
    ("popularity", "NOUN"): _n("populareco", "popular", suf="ec"),
    ("portrait", "NOUN"): _n("portreto", "portret"),
    ("poster", "NOUN"): _n("afiŝo", "afiŝ"),
    ("poverty", "NOUN"): _n("malriĉeco", "riĉ", pre="mal", suf="ec"),
    ("prediction", "NOUN"): _n("antaŭdiro", "antaŭdir", pre="antaŭ"),
    ("principal", "NOUN"): _n("ĉefo", "ĉef", c=_M, note="school principal; financial principal = kapitalo"),
    ("privacy", "NOUN"): _n("privateco", "privat", suf="ec"),
    ("process", "NOUN"): _n("procezo", "procez"),
    ("profile", "NOUN"): _n("profilo", "profil"),
    ("psychologist", "NOUN"): _n("psikologo", "psikolog"),
    ("psychology", "NOUN"): _n("psikologio", "psikologi"),
    ("quotation", "NOUN"): _n("citaĵo", "cit", suf="aĵ"),
    ("recipe", "NOUN"): _n("recepto", "recept"),
    ("recommendation", "NOUN"): _n("rekomendo", "rekomend"),
    ("reporter", "NOUN"): _n("raportisto", "raport", suf="ist"),
    ("researcher", "NOUN"): _n("esploristo", "esplor", suf="ist"),
    ("ring", "NOUN"): _n("ringo", "ring", c=_M, note="finger ring; bell ring = sonorilo"),
    ("robot", "NOUN"): _n("roboto", "robot"),
    ("row", "NOUN"): _n("vico", "vic"),
    ("sandwich", "NOUN"): _n("sandviĉo", "sandviĉ"),
    ("satellite", "NOUN"): _n("satelito", "satelit"),
    ("script", "NOUN"): _n("scenaro", "scenar", c=_M, note="screenplay; writing system = skribo"),
    ("sculpture", "NOUN"): _n("skulptaĵo", "skulpt", suf="aĵ"),
    ("second", "NOUN"): _n("sekundo", "sekund"),
    ("sequence", "NOUN"): _n("sinsekvo", "sinsekvoj", c=_M),
    ("setting", "NOUN"): _n("aranĝo", "aranĝ", c=_M),
    ("similarity", "NOUN"): _n("simileco", "simil", suf="ec"),
    ("ski", "NOUN"): _n("skio", "ski"),
    ("skiing", "NOUN"): _n("skiado", "ski", suf="ad"),
    ("slave", "NOUN"): _n("sklavo", "sklav"),
    ("smartphone", "NOUN"): _n("saĝtelefono", "saĝtelefon", pre="saĝ", c=_M),
    ("sneaker", "NOUN"): _n("sportoŝuo", "sportoŝu", pre="sporto", c=_M),
    ("soccer", "NOUN"): _n("futbalo", "futbal"),
    ("species", "NOUN"): _n("specio", "speci"),
    ("spending", "NOUN"): _n("elspezado", "elspezo", pre="el", suf="ad"),
    ("sponsor", "NOUN"): _n("sponsoro", "sponsor"),
    ("stadium", "NOUN"): _n("stadiono", "stadion"),
    ("statistic", "NOUN"): _n("statistiko", "statistik"),
    ("subway", "NOUN"): _n("metroo", "metro"),
    ("surgery", "NOUN"): _n("kirurgio", "kirurgi"),
    ("symptom", "NOUN"): _n("simptomo", "simptom"),
    ("t-shirt", "NOUN"): _n("T-ĉemizo", "T-ĉemiz"),
    ("tale", "NOUN"): _n("rakonto", "rakont"),
    ("talent", "NOUN"): _n("talento", "talent"),
    ("tear", "NOUN"): _n("larmo", "larm"),
    ("teenager", "NOUN"): _n("adoleskanto", "adoleskant"),
    ("tennis", "NOUN"): _n("teniso", "tenis"),
    ("theater", "NOUN"): _n("teatro", "teatr"),
    ("therapy", "NOUN"): _n("terapio", "terapi"),
    ("tourism", "NOUN"): _n("turismo", "turism"),
    ("trainer", "NOUN"): _n("trejnisto", "trejn", suf="ist"),
    ("transition", "NOUN"): _n("transiro", "transir", pre="trans"),
    ("trash", "NOUN"): _n("rubaĵo", "rub", suf="aĵ"),
    ("traveler", "NOUN"): _n("vojaĝanto", "vojaĝ", suf="ant"),
    ("update", "NOUN"): _n("ĝisdatigo", "ĝisdatig", pre="ĝis"),
    ("venue", "NOUN"): _n("aranĝejo", "aranĝej", suf="ej", c=_M),
    ("viewer", "NOUN"): _n("spektanto", "spektant"),
    ("vitamin", "NOUN"): _n("vitamino", "vitamin"),
    ("volunteer", "NOUN"): _n("volontulo", "voluntul"),
    ("wildlife", "NOUN"): _n("sovaĝfaŭno", "sovaĝfaŭn", pre="sovaĝ", c=_M),
    ("wind", "NOUN"): _n("vento", "vent"),
    ("wound", "NOUN"): _n("vundo", "vund"),
    # Verbs
    ("analyze", "VERB"): _v("analizi", "analiz"),
    ("assess", "VERB"): _v("taksi", "taks"),
    ("beg", "VERB"): _v("peti", "pet", c=_M, note="polite request; to beg (alms) = almozpeti"),
    ("center", "VERB"): _v("centri", "centr"),
    ("cite", "VERB"): _v("citi", "cit"),
    ("consume", "VERB"): _v("konsumi", "konsum"),
    ("detect", "VERB"): _v("detekti", "detekt"),
    ("do", "VERB"): _v("fari", "far"),
    ("donate", "VERB"): _v("donaci", "donaci"),
    ("download", "VERB"): _v("elŝuti", "elŝut", pre="el"),
    ("edit", "VERB"): _v("redakti", "redakt"),
    ("enhance", "VERB"): _v("plibonigi", "plibonig", pre="pli", suf="ig"),
    ("evaluate", "VERB"): _v("evalui", "evalu", c=_M),
    ("favor", "VERB"): _v("favori", "favor"),
    ("graduate", "VERB"): _v("diplomiĝi", "diplom", suf="iĝ"),
    ("greet", "VERB"): _v("saluti", "salut"),
    ("honor", "VERB"): _v("honori", "honor"),
    ("inspire", "VERB"): _v("inspiri", "inspir"),
    ("last", "VERB"): _v("daŭri", "daŭr"),
    ("lead", "VERB"): _v("gvidi", "gvid"),
    ("lie", "VERB"): _v("kuŝi", "kuŝ", c=_M, note="to recline; to tell a lie = mensogi"),
    ("live", "VERB"): _v("loĝi", "loĝ"),
    ("lower", "VERB"): _v("malaltigi", "alt", pre="mal", suf="ig"),
    ("modify", "VERB"): _v("modifi", "modif"),
    ("pace", "VERB"): _v("paŝi", "paŝ"),
    ("participate", "VERB"): _v("partopreni", "partopreni", pre="parto"),
    ("process", "VERB"): _v("pritrakti", "pritrak", pre="pri", c=_M),
    ("recycle", "VERB"): _v("recikligi", "reciklig", suf="ig"),
    ("refuse", "VERB"): _v("rifuzi", "rifuz"),
    ("ring", "VERB"): _v("sonorigi", "sonorig", suf="ig"),
    ("row", "VERB"): _v("remi", "rem"),
    ("scan", "VERB"): _v("skani", "skan"),
    ("ski", "VERB"): _v("skii", "ski"),
    ("sponsor", "VERB"): _v("sponsori", "sponsor"),
    ("submit", "VERB"): _v("submeti", "submet", pre="sub"),
    ("summarize", "VERB"): _v("resumi", "resum"),
    ("tear", "VERB"): _v("ŝiri", "ŝir"),
    ("update", "VERB"): _v("ĝisdatigi", "ĝisdatig", pre="ĝis", suf="ig"),
    ("volunteer", "VERB"): _v("volontuli", "voluntul"),
    ("wind", "VERB"): _v("sinui", "sinu", pre="si", c=_M),
    ("wound", "VERB"): _v("vundi", "vund"),
    # Adjectives
    ("awesome", "ADJ"): _a("mirinda", "mirind"),
    ("blond", "ADJ"): _a("blonda", "blond"),
    ("classical", "ADJ"): _a("klasika", "klasik"),
    ("close", "ADJ"): _a("proksima", "proksim", c=_M, note="near; closed = fermita"),
    ("colored", "ADJ"): _a("kolora", "kolor"),
    ("component", "ADJ"): None,  # no ADJ sense in Esperanto
    ("consistent", "ADJ"): _a("konsekvenca", "konsekvenc"),
    ("convinced", "ADJ"): _a("konvinkita", "konvink", suf="it"),
    ("corporate", "ADJ"): _a("kompania", "kompani"),
    ("creative", "ADJ"): _a("kreiva", "kreiv"),
    ("decent", "ADJ"): _a("deca", "dec"),
    ("delicious", "ADJ"): _a("bongusta", "bongust", pre="bon"),
    ("downtown", "ADJ"): _a("urbocentra", "urbocentr", pre="urbo"),
    ("educational", "ADJ"): _a("eduka", "eduk"),
    ("ethical", "ADJ"): _a("etika", "etik"),
    ("everyday", "ADJ"): _a("ĉiutaga", "ĉiutag", pre="ĉiu"),
    ("external", "ADJ"): _a("ekstera", "ekster"),
    ("fantastic", "ADJ"): _a("fantasta", "fantas"),
    ("fascinating", "ADJ"): _a("fascina", "fascin"),
    ("favorite", "ADJ"): _a("ŝatata", "ŝat", suf="at"),
    ("flexible", "ADJ"): _a("fleksebla", "flekseb", suf="ebl"),
    ("folk", "ADJ"): None,
    ("gray", "ADJ"): _a("griza", "griz"),
    ("historic", "ADJ"): _a("historia", "histori"),
    ("horrible", "ADJ"): _a("terura", "terur"),
    ("included", "ADJ"): _a("inkluzivita", "inkluziv", suf="it"),
    ("incredible", "ADJ"): _a("nekredebla", "kredebl", pre="ne", suf="ebl"),
    ("intense", "ADJ"): _a("intensa", "intens"),
    ("last", "ADJ"): _a("lasta", "last"),
    ("leading", "ADJ"): _a("ĉefa", "ĉef"),
    ("live", "ADJ"): _a("rekta", "rekt", c=_M, note="live broadcast; alive = vivanta"),
    ("long-term", "ADJ"): _a("longdaŭra", "longdaŭr", pre="long"),
    ("multiple", "ADJ"): _a("multobla", "multob", pre="mult", suf="obl"),
    ("narrative", "ADJ"): _a("rakonta", "rakont"),
    ("native", "ADJ"): _a("indiĝena", "indiĝen"),
    ("numerous", "ADJ"): _a("multnombra", "multnombr", pre="mult"),
    ("overseas", "ADJ"): _a("eksterlando", "eksterland", pre="ekster", c=_L, note="better: 'transocean-a'"),
    ("percent", "ADJ"): None,
    ("plus", "ADJ"): _a("plusa", "plus"),
    ("prime", "ADJ"): _a("ĉefa", "ĉef"),
    ("principal", "ADJ"): _a("ĉefa", "ĉef"),
    ("reliable", "ADJ"): _a("fidinda", "fidind"),
    ("scary", "ADJ"): _a("timiga", "timig", suf="ig"),
    ("second", "ADJ"): None,  # ordinal; Esperanto uses 'dua'
    ("solar", "ADJ"): _a("suna", "sun"),
    ("talented", "ADJ"): _a("talenta", "talent"),
    ("teenage", "ADJ"): _a("adoleskanta", "adoleskant"),
    ("used", "ADJ"): _a("uzata", "uz", suf="at"),
    ("virtual", "ADJ"): _a("virtuala", "virtual"),
    ("visual", "ADJ"): _a("vida", "vid"),
    ("wealthy", "ADJ"): _a("riĉa", "riĉ"),
    ("worldwide", "ADJ"): _a("tutmonda", "tutmond", pre="tut"),
    # Adverbs
    ("afterward", "ADV"): _r("poste", "post"),
    ("anymore", "ADV"): _r("plu", "plu", c=_M, note="usually 'ne plu' (no longer)"),
    ("close", "ADV"): _r("proksime", "proksim"),
    ("downtown", "ADV"): _r("urbocentre", "urbocentr", pre="urbo"),
    ("fortunately", "ADV"): _r("bonŝance", "bonŝanc", pre="bon"),
    ("furthermore", "ADV"): _r("krome", "krom"),
    ("incredibly", "ADV"): _r("nekredeble", "kredebl", pre="ne", suf="ebl"),
    ("last", "ADV"): _r("laste", "last"),
    ("live", "ADV"): _r("rekte", "rekt", c=_M),
    ("overseas", "ADV"): _r("eksterlande", "eksterland", pre="ekster"),
    ("second", "ADV"): _r("due", "du"),
    ("worldwide", "ADV"): _r("tutmonde", "tutmond", pre="tut"),
    # Interjections
    ("ah", "INTJ"): _i("ha", "ha"),
    ("hey", "INTJ"): _i("hej", "hej"),
    ("wow", "INTJ"): _i("ho", "ho"),
}


def _load_existing_roots(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """Build a map of english_word -> (eo_root, eo_word) from rows that have data."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT word, esperanto_root, esperanto_word
        FROM vocabulary
        WHERE esperanto_word IS NOT NULL
        """
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _root_similarity_proposal(
    word: str, pos: str, existing_roots: dict[str, tuple[str, str]]
) -> EoProposal | None:
    """Derive a proposal by truncating the English word and checking for matches.

    Heuristic: strip common suffixes (-tion, -ment, -ness, -ity, -er, -or, -ing,
    -ed, -ly) from both the target word and existing words, then look for a
    shared stem that has a known Esperanto root.
    """
    suffixes = ["tion", "ment", "ness", "ity", "ness", "ing", "tion", "er", "or", "ly", "ed", "al", "ful"]
    stem = word.lower()
    for suf in suffixes:
        if stem.endswith(suf) and len(stem) - len(suf) >= 3:
            stem = stem[: -len(suf)]
            break

    for existing_word, (eo_root, eo_word) in existing_roots.items():
        existing_stem = existing_word.lower()
        for suf in suffixes:
            if existing_stem.endswith(suf) and len(existing_stem) - len(suf) >= 3:
                existing_stem = existing_stem[: -len(suf)]
                break
        if existing_stem == stem and stem:
            pos_ending = {"NOUN": "o", "VERB": "i", "ADJ": "a", "ADV": "e"}.get(pos, "o")
            derived_word = eo_root + pos_ending
            return EoProposal(
                eo_word=derived_word,
                eo_root=eo_root,
                eo_ending=pos_ending,
                eo_prefix="",
                eo_suffix="",
                eo_pos=pos,
                confidence="low",
                method="root_similarity",
                notes=f"derived from '{existing_word}' → '{eo_word}'",
            )
    return None


def run(db_path: Path = DB_PATH, out_path: Path = OUT_PATH) -> tuple[int, int]:
    """Run enrichment and write candidates.

    Returns:
        (matched, unmatched) counts.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, word, pos, cefr_level, tier, source,
               wordnet_synset, wordnet_definition
        FROM vocabulary
        WHERE esperanto_word IS NULL
        ORDER BY word, pos
        """
    )
    pending = cur.fetchall()

    existing_roots = _load_existing_roots(conn)
    conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    matched = 0
    unmatched = 0
    skipped_no_eo = 0

    with out_path.open("w", encoding="utf-8") as fh:
        for row in pending:
            word, pos = row["word"], row["pos"]
            key = (word, pos)

            proposal: EoProposal | None = MAPPING.get(key, _SENTINEL)

            if proposal is _SENTINEL:
                # Not in hardcoded map — try root similarity
                proposal = _root_similarity_proposal(word, pos, existing_roots)

            if proposal is None:
                # Explicitly no Esperanto equivalent (e.g. 'a' DET)
                skipped_no_eo += 1
                record = {
                    "v1_id": row["id"],
                    "word": word,
                    "pos": pos,
                    "cefr_level": row["cefr_level"],
                    "tier": row["tier"],
                    "source": row["source"],
                    "wordnet_synset": row["wordnet_synset"],
                    "wordnet_definition": row["wordnet_definition"],
                    "eo_word": None,
                    "eo_root": None,
                    "eo_ending": None,
                    "eo_prefix": None,
                    "eo_suffix": None,
                    "eo_pos": None,
                    "confidence": None,
                    "method": "no_eo_equivalent",
                    "notes": "no Esperanto equivalent exists or is ambiguous",
                    "approved": False,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                continue

            if proposal is not None:
                matched += 1
            else:
                unmatched += 1

            record = {
                "v1_id": row["id"],
                "word": word,
                "pos": pos,
                "cefr_level": row["cefr_level"],
                "tier": row["tier"],
                "source": row["source"],
                "wordnet_synset": row["wordnet_synset"],
                "wordnet_definition": row["wordnet_definition"],
                "eo_word": proposal.eo_word if proposal else None,
                "eo_root": proposal.eo_root if proposal else None,
                "eo_ending": proposal.eo_ending if proposal else None,
                "eo_prefix": proposal.eo_prefix if proposal else None,
                "eo_suffix": proposal.eo_suffix if proposal else None,
                "eo_pos": proposal.eo_pos if proposal else None,
                "confidence": proposal.confidence if proposal else None,
                "method": proposal.method if proposal else "unmatched",
                "notes": proposal.notes if proposal else "",
                "approved": False,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return matched, unmatched + skipped_no_eo


_SENTINEL: EoProposal | None = object()  # type: ignore[assignment]


def main() -> None:
    """CLI entry point."""
    matched, unmatched = run()
    total = matched + unmatched
    print(f"Pending rows processed : {total}")
    print(f"  Automatically matched: {matched}")
    print(f"  Unmatched / no-equiv : {unmatched}")
    print(f"Candidates written to  : {OUT_PATH}")
    print("Review and set 'approved': true before running migrate_v1_to_v2.py")


if __name__ == "__main__":
    main()
