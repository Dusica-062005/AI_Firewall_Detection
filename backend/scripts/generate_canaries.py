"""Generate the leak-canary sets: app/canaries/canaries.json and canaries_holdout.json (committed).

    python scripts/generate_canaries.py              # both sets
    python scripts/generate_canaries.py --set main   # or --set holdout

Deterministic (fixed seed, no network): running it twice gives byte-identical output.
Every name, ID and number is invented. Patient IDs start with P9, mobile numbers with 9 and
Aadhaar numbers with 9999, so a canary can never be mistaken for a real identity.

Templates are hospital scheduling and triage calls with {slots}. A planted value is never
part of a template's fixed text, so every recorded span is exact.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.canaries.models import CANARY_FILE, HOLDOUT_FILE, CanarySet  # noqa: E402

SEED = 20261103
VERSION = "canaries-v1"
PROFILE = "standard"  # the profile whose policies permit a cloud path, so leaks are possible

# ---- Fake value pools ---------------------------------------------------------------------

LATIN_FIRST = [
    "Arjun", "Kavya", "Rohan", "Ananya", "Vikram", "Meera", "Siddharth", "Nandini", "Farhan", "Lakshmi",
    "Rahul", "Ishita", "Karthik", "Divya", "Aditya", "Pooja", "Manoj", "Sneha", "Harish", "Tanvi",
    "Naveen", "Shalini", "Gaurav", "Revathi", "Imran", "Deepa", "Varun", "Aparna", "Suresh", "Nisha",
    "Emily", "Lucas", "Hannah", "Omar", "Grace", "Tobias", "Chiara", "Mateo",
]
LATIN_LAST = [
    "Mehta", "Rao", "Iyer", "Nair", "Kulkarni", "Reddy", "Banerjee", "Menon", "Gowda", "Pillai",
    "Chatterjee", "Hegde", "Joshi", "Krishnan", "Shetty", "Qureshi", "Bhat", "Subramanian", "Deshpande",
    "Venkatesh", "Carter", "Moreau", "Weiss", "Haddad", "Lindqvist", "Okafor",
]
NATIVE_NAMES = {
    "hi": ["अर्जुन मेहता", "कविता राव", "रोहन वर्मा", "अनन्या जोशी", "विक्रम सिंह", "मीरा अग्रवाल",
           "सिद्धार्थ गुप्ता", "नंदिनी शर्मा"],
    "kn": ["ಅರ್ಜುನ್ ಗೌಡ", "ಕಾವ್ಯ ಹೆಗ್ಡೆ", "ರೋಹನ್ ಶೆಟ್ಟಿ", "ಅನನ್ಯ ಭಟ್", "ವಿಕ್ರಮ್ ರಾವ್", "ಮೀರಾ ಕುಲಕರ್ಣಿ",
           "ನವೀನ್ ರೆಡ್ಡಿ", "ದಿವ್ಯಾ ನಾಯಕ್"],
    "ta": ["அர்ஜுன் கிருஷ்ணன்", "காவ்யா ஐயர்", "ரோஹன் பிள்ளை", "அனன்யா சுப்ரமணியன்", "விக்ரம் ராஜா",
           "மீரா வெங்கடேஷ்", "கார்த்திக் முருகன்", "திவ்யா சேகர்"],
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

# ---- Spoken digit vocabularies --------------------------------------------------------------

EN_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
HI_LATIN_WORDS = ["shunya", "ek", "do", "teen", "char", "paanch", "chhe", "saat", "aath", "nau"]
KN_LATIN_WORDS = ["sonne", "ondu", "eradu", "mooru", "naalku", "aidu", "aaru", "elu", "entu", "ombattu"]
TA_LATIN_WORDS = ["poojyam", "onnu", "rendu", "moonu", "naalu", "anju", "aaru", "ezhu", "ettu", "onbadhu"]
HI_NATIVE_WORDS = ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ"]
KN_NATIVE_WORDS = ["ಸೊನ್ನೆ", "ಒಂದು", "ಎರಡು", "ಮೂರು", "ನಾಲ್ಕು", "ಐದು", "ಆರು", "ಏಳು", "ಎಂಟು", "ಒಂಬತ್ತು"]
TA_NATIVE_WORDS = ["பூஜ்ஜியம்", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"]

SPOKEN = {
    ("en", "latin"): [EN_WORDS],
    ("hinglish", "latin"): [HI_LATIN_WORDS, EN_WORDS],
    ("hi", "latin"): [HI_LATIN_WORDS, EN_WORDS],
    ("hi", "native"): [HI_NATIVE_WORDS],
    ("kn", "latin"): [KN_LATIN_WORDS, EN_WORDS],
    ("kn", "native"): [KN_NATIVE_WORDS],
    ("ta", "latin"): [TA_LATIN_WORDS, EN_WORDS],
    ("ta", "native"): [TA_NATIVE_WORDS],
}
NATIVE_DIGIT_BASE = {"hi": 0x0966, "kn": 0x0CE6, "ta": 0x0BE6}

# Filler a caller says between the two halves of a split patient ID.
SPLIT_FILLER = {
    ("en", "latin"): [". Sorry, the line dropped. It's ", ". Wait, then ", ". Sorry, the rest is "],
    ("hinglish", "latin"): [". Sorry, phir se, ", ". Ek second, aage ", ". Haan, baaki hai "],
    ("hi", "latin"): [". Maaf kijiye, aage ", ". Ek minute, baaki "],
    ("hi", "native"): ["। माफ़ कीजिए, आगे ", "। एक मिनट, बाकी "],
    ("kn", "latin"): [". Kshamisi, mundhe ", ". Ondu nimisha, uLidaddu "],
    ("kn", "native"): [". ಕ್ಷಮಿಸಿ, ಮುಂದೆ ", ". ಒಂದು ನಿಮಿಷ, ಉಳಿದದ್ದು "],
    ("ta", "latin"): [". Mannikkavum, adhu ", ". Oru nimisham, meedhi "],
    ("ta", "native"): [". மன்னிக்கவும், அது ", ". ஒரு நிமிடம், மீதி "],
}
# Some fillers cross two sentence boundaries ("... dropped. It's"); the normalizer joins split
# parts across one boundary only, so those calls are expected, honest misses.

# ---- Templates ---------------------------------------------------------------------------------

TEMPLATES = {
    ("en", "latin"): [
        "Hi, this is {name}. My patient ID is {pid} and I need to move my follow-up to next week.",
        "Good morning, I'm calling for my mother. Her name is {name} and her date of birth is {dob}. She has a cardiology review on Friday.",
        "Hello, {name} here. You can reach me on {phone} if the doctor is running late today.",
        "I want to confirm my blood test results. Patient ID {pid}, and please email the report to {email}.",
        "This is {name}, date of birth {dob}. My patient number is {pid}. Can I see Dr. Rao on Monday?",
        "My Aadhaar number is {aadhaar} for the insurance form, and my mobile is {phone}.",
        "Hi, I missed a call from the clinic. My name is {name}, phone {phone}. Patient ID is {pid}.",
        "Can you send the discharge summary to {email}? It's for {name}.",
        "I'm calling about my son {name}. He was born on {dob} and needs his vaccination booked.",
        "The nurse asked me to call back. Patient ID {pid}. I have had a fever since yesterday.",
        "Please update my contact number to {phone}. The old one no longer works. Thanks, {name}.",
        "I need a copy of my prescription. I'm {name}, Aadhaar {aadhaar}, date of birth {dob}.",
        "Hello, it's {name} again. {name} with the knee appointment. My patient ID is {pid}.",
        "Could someone call me on {phone} about the MRI slot? My patient ID is {pid} and my email is {email}.",
    ],
    ("hinglish", "latin"): [
        "Hello, main {name} bol raha hoon. Mera patient ID {pid} hai, appointment reschedule karna hai.",
        "Namaste, meri date of birth {dob} hai. Mujhe Dr. Iyer se Thursday ko milna hai, naam {name} hai.",
        "Mera mobile number {phone} hai, report ready ho toh please call kar dena.",
        "Haan ji, patient ID {pid} hai aur report {email} pe bhej dijiye.",
        "Main apni beti {name} ke liye call kar rahi hoon, uska janam {dob} ko hua tha.",
        "Mera Aadhaar number {aadhaar} hai, insurance claim ke liye chahiye.",
        "Sir, {name} bol rahi hoon, mera number {phone} hai, kal se bukhar hai.",
        "Patient ID {pid} hai, mujhe blood test ka result janna hai. Mera naam {name} hai.",
        "Please mera contact {phone} update kar dijiye, purana number band ho gaya hai.",
        "Main {name}, DOB {dob}, Aadhaar {aadhaar}. Pharmacy se dawai leni hai.",
        "Doctor ne bola tha call karne ko, patient ID {pid}, mobile {phone}.",
    ],
    ("hi", "latin"): [
        "Namaste, mera naam {name} hai. Mera patient ID {pid} hai, mujhe agle hafte ka samay chahiye.",
        "Meri janam tithi {dob} hai aur mera naam {name} hai, doctor sahab se milna hai.",
        "Mera phone number {phone} hai, kripya mujhe vapas phone kijiye.",
        "Mera aadhaar number {aadhaar} hai, beema ke kaagaz ke liye chahiye.",
        "Patient ID {pid} hai, meri report {email} par bhej dijiye.",
        "Main {name} ki maa bol rahi hoon, uska patient ID {pid} hai aur mobile {phone} hai.",
    ],
    ("hi", "native"): [
        "नमस्ते, मेरा नाम {name} है। मेरा patient ID {pid} है, मुझे अगले हफ्ते का समय चाहिए।",
        "मेरी जन्म तिथि {dob} है, मुझे डॉक्टर से मिलना है।",
        "मेरा मोबाइल नंबर {phone} है, कृपया वापस फ़ोन करें।",
        "मेरा आधार नंबर {aadhaar} है, बीमा के लिए चाहिए।",
        "{name} बोल रहा हूँ, रिपोर्ट {email} पर भेज दीजिए।",
        "मरीज़ आईडी {pid} है और फ़ोन नंबर {phone} है।",
    ],
    ("kn", "latin"): [
        "Namaskara, nanna hesaru {name}. Nanna patient ID {pid}, mundina vaara appointment beku.",
        "Nanna date of birth {dob}, doctor jothe maathaadabeku.",
        "Nanna mobile number {phone}, dayavittu call maadi.",
        "Nanna Aadhaar number {aadhaar}, insurance ge beku.",
        "Report annu {email} ge kalisi, nanna hesaru {name}.",
        "Patient ID {pid}, phone {phone}, naale bartini.",
    ],
    ("kn", "native"): [
        "ನಮಸ್ಕಾರ, ನನ್ನ ಹೆಸರು {name}. ನನ್ನ patient ID {pid}, ಮುಂದಿನ ವಾರ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಬೇಕು.",
        "ನನ್ನ ಜನ್ಮ ದಿನಾಂಕ {dob}, ವೈದ್ಯರನ್ನು ಭೇಟಿ ಮಾಡಬೇಕು.",
        "ನನ್ನ ಮೊಬೈಲ್ ನಂಬರ್ {phone}, ದಯವಿಟ್ಟು ಕರೆ ಮಾಡಿ.",
        "ನನ್ನ ಆಧಾರ್ ಸಂಖ್ಯೆ {aadhaar}, ವಿಮೆಗೆ ಬೇಕು.",
        "ವರದಿಯನ್ನು {email} ಗೆ ಕಳುಹಿಸಿ, ನಾನು {name}.",
        "ರೋಗಿ ಐಡಿ {pid}, ಫೋನ್ {phone}.",
    ],
    ("ta", "latin"): [
        "Vanakkam, en peyar {name}. En patient ID {pid}, adutha vaaram appointment venum.",
        "En date of birth {dob}, doctor-ai paarkanum.",
        "En mobile number {phone}, thayavu seidhu call pannunga.",
        "En Aadhaar number {aadhaar}, insurance-kku venum.",
        "Report-ai {email} -kku anuppunga, naan {name}.",
        "Patient ID {pid}, phone {phone}, naalai varuven.",
    ],
    ("ta", "native"): [
        "வணக்கம், என் பெயர் {name}. என் patient ID {pid}, அடுத்த வாரம் சந்திப்பு வேண்டும்.",
        "என் பிறந்த தேதி {dob}, மருத்துவரைப் பார்க்க வேண்டும்.",
        "என் மொபைல் எண் {phone}, தயவுசெய்து அழைக்கவும்.",
        "என் ஆதார் எண் {aadhaar}, காப்பீட்டுக்கு வேண்டும்.",
        "அறிக்கையை {email} க்கு அனுப்புங்கள், நான் {name}.",
        "நோயாளி ஐடி {pid}, தொலைபேசி {phone}.",
    ],
}

# Held-out set (C0): new phrasings written separately from the main templates, so detection
# changes can be checked for overfitting. Never tune recognizers against this set's misses.
HOLDOUT_TEMPLATES = {
    ("en", "latin"): [
        "Calling on behalf of {name}; the number on her hospital card is patient ID {pid}.",
        "Hey, it's {name}. Could the clinic text me at {phone} when the lab results arrive?",
        "For the claim form, my Aadhaar is {aadhaar} and I was born on {dob}.",
        "I'd like the discharge letter emailed to {email}, please. Patient ID {pid}.",
        "Pharmacy here, confirming a refill for {name}, born {dob}, reachable on {phone}.",
        "Patient {name} missed today's physiotherapy slot; her MRN is {pid}.",
        "Could you move the dental check-up for {name}? Patient ID {pid}, mobile {phone}.",
        "My daughter {name} has a rash since Sunday. Her birthday is {dob}.",
    ],
    ("hinglish", "latin"): [
        "Haan, {name} ki taraf se bol raha hoon, unka patient ID {pid} hai.",
        "Report aa gayi kya? Mera email {email} hai, wahan bhej do.",
        "Mere papa {name}, unki DOB {dob} hai, unko checkup chahiye.",
        "Aadhaar {aadhaar} hai mera, claim form ke liye.",
        "Mujhe callback chahiye is number pe: {phone}.",
        "Kal ka appointment cancel karna hai, patient ID {pid}, naam {name}.",
    ],
    ("hi", "latin"): [
        "Mere bete ka naam {name} hai, uska patient ID {pid} hai.",
        "Kripya is number par sampark karein: {phone}.",
        "Meri janm tithi {dob} hai, mujhe jaanch karwani hai.",
    ],
    ("hi", "native"): [
        "मेरे पिता का नाम {name} है, उनका patient ID {pid} है।",
        "कृपया इस नंबर पर फ़ोन करें: {phone}।",
        "मेरा आधार {aadhaar} है और ईमेल {email} है।",
    ],
    ("kn", "latin"): [
        "Nanna appa hesaru {name}, avara patient ID {pid}.",
        "Ee number ge call maadi: {phone}.",
        "Nanna janma dinaanka {dob}, check-up beku.",
    ],
    ("kn", "native"): [
        "ನನ್ನ ತಂದೆಯ ಹೆಸರು {name}, ಅವರ patient ID {pid}.",
        "ಈ ಸಂಖ್ಯೆಗೆ ಕರೆ ಮಾಡಿ: {phone}.",
        "ನನ್ನ ಆಧಾರ್ {aadhaar}, ಇಮೇಲ್ {email}.",
    ],
    ("ta", "latin"): [
        "En appa peyar {name}, avar patient ID {pid}.",
        "Indha number-ku call pannunga: {phone}.",
        "En pirandha thedhi {dob}, check-up venum.",
    ],
    ("ta", "native"): [
        "என் அப்பா பெயர் {name}, அவர் patient ID {pid}.",
        "இந்த எண்ணுக்கு அழைக்கவும்: {phone}.",
        "என் ஆதார் {aadhaar}, மின்னஞ்சல் {email}.",
    ],
}

SLOT_TYPES = {
    "name": "PERSON",
    "pid": "PATIENT_ID",
    "phone": "PHONE_NUMBER",
    "aadhaar": "GOVERNMENT_ID",
    "dob": "DATE_OF_BIRTH",
    "email": "EMAIL_ADDRESS",
}
NUMERIC_SLOTS = ("pid", "phone", "aadhaar")
_SLOT = re.compile(r"\{(\w+)\}")

# (language, script, difficulty, count): 200 calls, 95 of them non-plain.
SCHEDULE = [
    ("en", "latin", "plain", 60), ("en", "latin", "spelled_digits", 20),
    ("en", "latin", "split_id", 12), ("en", "latin", "mixed", 8),
    ("hinglish", "latin", "hinglish", 15), ("hinglish", "latin", "spelled_digits", 5),
    ("hinglish", "latin", "split_id", 3), ("hinglish", "latin", "mixed", 2),
]
for _lang in ("hi", "kn", "ta"):
    SCHEDULE += [
        (_lang, "latin", "plain", 8), (_lang, "latin", "spelled_digits", 3),
        (_lang, "latin", "split_id", 1), (_lang, "latin", "mixed", 1),
        (_lang, "native", "plain", 7), (_lang, "native", "spelled_digits", 3),
        (_lang, "native", "split_id", 1), (_lang, "native", "mixed", 1),
    ]

# Held-out set: 100 calls, 15 per non-English language.
HOLDOUT_SCHEDULE = [
    ("en", "latin", "plain", 24), ("en", "latin", "spelled_digits", 8),
    ("en", "latin", "split_id", 5), ("en", "latin", "mixed", 3),
    ("hinglish", "latin", "hinglish", 9), ("hinglish", "latin", "spelled_digits", 3),
    ("hinglish", "latin", "split_id", 2), ("hinglish", "latin", "mixed", 1),
]
for _lang in ("hi", "kn", "ta"):
    HOLDOUT_SCHEDULE += [
        (_lang, "latin", "plain", 5), (_lang, "latin", "spelled_digits", 2), (_lang, "latin", "split_id", 1),
        (_lang, "native", "plain", 4), (_lang, "native", "spelled_digits", 2), (_lang, "native", "mixed", 1),
    ]


@dataclass(frozen=True)
class SetConfig:
    seed: int
    version: str
    templates: dict
    schedule: list
    path: Path


SETS = {
    "main": SetConfig(SEED, VERSION, TEMPLATES, SCHEDULE, CANARY_FILE),
    "holdout": SetConfig(20261117, "canaries-holdout-v1", HOLDOUT_TEMPLATES, HOLDOUT_SCHEDULE, HOLDOUT_FILE),
}


# ---- Value rendering ---------------------------------------------------------------------------

def digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def to_native(text: str, language: str) -> str:
    base = NATIVE_DIGIT_BASE[language]
    return "".join(chr(base + int(c)) if c.isdigit() else c for c in text)


def spell(rng: random.Random, number: str, language: str, script: str) -> str:
    """Speak a digit string, using "double" for English repeats now and then."""
    words = rng.choice(SPOKEN[(language, script)])
    out: list[str] = []
    i = 0
    while i < len(number):
        d = int(number[i])
        if words is EN_WORDS and i + 1 < len(number) and number[i + 1] == number[i] and rng.random() < 0.6:
            out.append(f"double {words[d]}")
            i += 2
            continue
        out.append(words[d])
        i += 1
    return " ".join(out)


class CallBuilder:
    """Concatenates text pieces and records the exact span of every planted surface part."""

    def __init__(self) -> None:
        self.text = ""
        self.planted: dict[str, dict] = {}

    def add(self, piece: str) -> None:
        self.text += piece

    def plant(self, slot: str, piece: str, canonical: str) -> None:
        start = len(self.text)
        self.text += piece
        entry = self.planted.setdefault(slot, {"type": SLOT_TYPES[slot], "canonical": canonical, "spans": []})
        entry["spans"].append([start, len(self.text)])


def make_values(rng: random.Random, slots: list[str], language: str, script: str) -> dict[str, str]:
    first, last = rng.choice(LATIN_FIRST), rng.choice(LATIN_LAST)
    native = script == "native"
    day, month, year = rng.randrange(1, 29), rng.randrange(1, 13), rng.randrange(1940, 2006)
    values = {
        "name": rng.choice(NATIVE_NAMES[language]) if native else f"{first} {last}",
        "pid": "P9" + digits(rng, 6),
        "phone": "9" + digits(rng, 9),
        "aadhaar": "9999" + digits(rng, 8),
        "dob": f"{day:02d}/{month:02d}/{year}",
        "dob_format": rng.choice(["slash", "dash", "month_first", "day_first"]),
        "email_user": f"{rng.choice(LATIN_FIRST).lower()}.{rng.choice(LATIN_LAST).lower()}{digits(rng, 2)}",
        "phone_format": rng.choice(["plus91", "grouped", "bare", "zero"]),
        "aadhaar_format": rng.choice(["spaced", "dashed"]),
        "native_digits": native and rng.random() < 0.5,
    }
    values["email"] = f"{values['email_user']}@example.org"
    return {k: v for k, v in values.items() if k in slots or k not in SLOT_TYPES}


def typed(slot: str, v: dict, language: str) -> str:
    """The typed (not spoken) surface form of a value."""
    if slot == "phone":
        p = v["phone"]
        surface = {
            "plus91": f"+91 {p[:5]} {p[5:]}", "grouped": f"{p[:5]} {p[5:]}", "bare": p, "zero": f"0{p[:5]} {p[5:]}",
        }[v["phone_format"]]
    elif slot == "aadhaar":
        a = v["aadhaar"]
        sep = " " if v["aadhaar_format"] == "spaced" else "-"
        surface = sep.join((a[:4], a[4:8], a[8:]))
    elif slot == "dob":
        day, month, year = v["dob"].split("/")
        surface = {
            "slash": v["dob"],
            "dash": f"{day}-{month}-{year}",
            "month_first": f"{MONTHS[int(month) - 1]} {int(day)}, {year}",
            "day_first": f"{int(day)} {MONTHS[int(month) - 1]} {year}",
        }[v["dob_format"]]
    else:
        surface = v[slot]
    if v["native_digits"] and slot in ("phone", "aadhaar", "dob"):
        surface = to_native(surface, language)
    return surface


def build_call(
    rng: random.Random, call_id: str, language: str, script: str, difficulty: str, all_templates: dict = TEMPLATES
) -> dict:
    templates = all_templates[(language, script)]
    if difficulty in ("split_id", "mixed"):
        templates = [t for t in templates if "{pid}" in t]
    elif difficulty == "spelled_digits":
        templates = [t for t in templates if any("{" + s + "}" in t for s in NUMERIC_SLOTS)]
    template = rng.choice(templates)
    slots = list(dict.fromkeys(_SLOT.findall(template)))
    v = make_values(rng, slots, language, script)

    spelled: set[str] = set()
    if difficulty == "spelled_digits":
        spelled.add(rng.choice([s for s in NUMERIC_SLOTS if s in slots]))
    elif difficulty == "mixed" and "phone" in slots:
        spelled.add("phone")
    split = difficulty in ("split_id", "mixed")

    builder = CallBuilder()
    cursor = 0
    for match in _SLOT.finditer(template):
        builder.add(template[cursor : match.start()])
        cursor = match.end()
        slot = match.group(1)
        if slot == "pid" and split:
            pid = v["pid"]
            head, tail = pid[:4], pid[4:]  # "P948" + "2913": the head is too short to be an ID
            builder.plant(slot, head, pid)
            builder.add(rng.choice(SPLIT_FILLER[(language, script)]))
            tail_text = spell(rng, tail, language, script) if difficulty == "mixed" else tail
            builder.plant(slot, tail_text, pid)
        elif slot == "pid" and "pid" in spelled:
            builder.plant(slot, "P " + spell(rng, v["pid"][1:], language, script), v["pid"])
        elif slot in spelled:
            builder.plant(slot, spell(rng, v[slot], language, script), v[slot])
        else:
            canonical = v[slot] if slot != "dob" else v["dob"]
            builder.plant(slot, typed(slot, v, language), canonical)
    builder.add(template[cursor:])

    for entry in builder.planted.values():
        for start, end in entry["spans"]:
            assert builder.text[start:end], f"{call_id}: empty span"
    return {
        "call_id": call_id,
        "language": language,
        "script": script,
        "difficulty": difficulty,
        "profile": PROFILE,
        "text": builder.text,
        "planted": list(builder.planted.values()),
    }


def build_canary_set(name: str = "main") -> dict:
    config = SETS[name]
    rng = random.Random(config.seed)
    calls = []
    for language, script, difficulty, count in config.schedule:
        for _ in range(count):
            calls.append(build_call(rng, f"can-{len(calls) + 1:04d}", language, script, difficulty, config.templates))
    return {"version": config.version, "generated_with_seed": config.seed, "calls": calls}


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", choices=[*SETS, "all"], default="all")
    for name in SETS if parser.parse_args().set == "all" else [parser.parse_args().set]:
        write_set(name)


def write_set(name: str) -> None:
    config = SETS[name]
    data = build_canary_set(name)
    CanarySet.model_validate(data)  # spans in range, 1-4 planted values, known types
    for call in data["calls"]:
        for p in call["planted"]:
            for start, end in p["spans"]:
                assert 0 <= start < end <= len(call["text"]), call["call_id"]
    config.path.write_bytes(render(data).encode("utf-8"))

    calls = data["calls"]
    non_plain = sum(c["difficulty"] != "plain" for c in calls)
    print(f"\nWrote {len(calls)} calls to {config.path.relative_to(BACKEND)} ({config.version}, seed {config.seed}).")
    print(f"Non-plain: {non_plain} ({non_plain / len(calls):.0%})")
    for label, key in (("language", lambda c: c["language"]), ("script", lambda c: f"{c['language']}/{c['script']}"),
                       ("difficulty", lambda c: c["difficulty"])):
        counts = Counter(key(c) for c in calls)
        print(f"By {label}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
    types = Counter(p["type"] for c in calls for p in c["planted"])
    print("Planted values: " + ", ".join(f"{k} {n}" for k, n in sorted(types.items())))


if __name__ == "__main__":
    main()
