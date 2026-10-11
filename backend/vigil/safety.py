"""What Vigil will not watch for. Checked before a request is compiled, again on the compiled spec, and on edits.

Vigil watches for objects, events and conditions ("a package on the step", "anyone without a hard hat",
"the bin is empty"). It does not watch for kinds of people, identify anyone, or watch private spaces. A request
that would do any of that is refused with a plain reason and a neutral way to ask instead.

The rules are a deterministic first line (fast, predictable, testable). The brain's compile step applies the same
policy in words and can refuse things the rules miss; either refusal stops the watch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PEOPLE = r"(?:person|people|someone|somebody|anyone|anybody|man|men|woman|women|girl|girls|boy|boys|guy|guys|lady|ladies|kid|kids|child|children|teen|teens|teenager|baby|adult|employee|worker|customer|visitor|individual|human)s?"


@dataclass
class Verdict:
    allowed: bool
    category: str = ""
    reason: str = ""
    suggestion: str = ""

    def out(self) -> dict:
        return {"allowed": self.allowed, "category": self.category, "reason": self.reason, "suggestion": self.suggestion}


RULES: list[tuple[str, str, str, str]] = [
    # (category, pattern, reason, suggestion)
    ("identity",
     r"\b(?:face ?recognition|facial recognition|recogni[sz]e (?:faces?|who|people|him|her|them)|identify (?:who|the person|people|him|her|them|faces?)|"
     r"who (?:is|was) (?:at|in|by|on)|track (?:him|her|them|that (?:man|woman|guy|person))|follow (?:him|her|them|the person|that person)|"
     r"where (?:he|she|they) go(?:es)?|stalk|license plate of (?:my|her|his)|my ex\b|ex-?(?:wife|husband|girlfriend|boyfriend))",
     "Vigil does not identify people or follow a particular person.",
     "Ask about the situation instead, e.g. \"Text me when someone is at the front door\"."),
    ("protected_traits",
     rf"\b(?:(?:a|an|any|the|every|some|young|old|older|asian|black|white|hispanic|latino|latina|arab|muslim|jewish|christian|gay|trans(?:gender)?|female|male|pregnant|disabled|elderly|fat|thin|skinny|pretty|hot|attractive|sexy|cute)\s+)?"
     r"(?:girl|girls|woman|women|lady|ladies|female|females|boy|boys|man|men|guy|guys|male|males)\b(?!\s+(?:wearing|without|with(?:out)? a|in a hard hat))"
     r"|\b(?:race|ethnicity|skin colou?r|religion|religious|hijab|turban|nationality|sexual orientation|gay|lesbian|transgender|pregnan\w*|disabilit\w*|wheelchair user|age of|how old)\b",
     "Vigil does not single out people by gender, race, religion, age or other personal traits.",
     "Watch for any person and what they are doing, e.g. \"Text me if anyone goes near the pool\"."),
    ("bodies",
     r"\b(?:naked|nude|nudity|undress\w*|topless|cleavage|bikini|lingerie|underwear|body shape|butt|breasts?|sexy|attractive|hot (?:girl|guy|woman|man)|"
     r"looks? (?:hot|good|pretty|sexy))\b",
     "Vigil does not watch people's bodies or appearance.",
     "Describe the object, event or safety rule you care about instead."),
    ("private_spaces",
     r"\b(?:bathroom|restroom|toilet|washroom|changing room|fitting room|locker room|shower|lactation room|someone'?s bedroom|neighbou?r'?s (?:house|yard|window|bedroom)|through (?:the|their|a) window)\b",
     "Vigil does not watch places where people expect privacy, or other people's homes.",
     "Point the camera at spaces you are responsible for, like an entrance, a dock or a stockroom."),
    ("covert",
     r"\b(?:spy(?:ing)? on|secretly|covert(?:ly)?|hidden camera|without (?:them|him|her|anyone) knowing|catch (?:my|her|him)|cheating)\b",
     "Vigil is for open, disclosed monitoring, not covert surveillance of people.",
     "Let people know the area is monitored, and watch for the event itself."),
    ("inference",
     r"\b(?:emotion|emotional|mood|angry|sad|depressed|drunk|on drugs|looks? suspicious|suspicious[- ]looking|criminal|illegal immigrant|homeless)\b",
     "Vigil does not guess emotions, intentions, health or social status from how someone looks.",
     "Watch for a concrete action, e.g. \"someone climbs the fence\" or \"a person is lying on the floor\"."),
    ("minors",
     r"\b(?:minor|minors|underage|little girl|little boy)\b|\b(?:child|children|kids?|baby|toddler)\b.{0,24}\b(?:chang\w*|undress\w*|bath\w*|naked|nude)\b",
     "Vigil does not single out children.",
     "Watch for anyone, e.g. \"Text me if anyone goes near the pool\"."),
]

_COMPILED = [(c, re.compile(p, re.I), r, s) for c, p, r, s in RULES]


def check_text(text: str) -> Verdict:
    t = " ".join((text or "").split())
    for category, pat, reason, suggestion in _COMPILED:
        if pat.search(t):
            return Verdict(False, category, reason, suggestion)
    return Verdict(True)


def check_spec(spec: dict) -> Verdict:
    """The compiled watch can be stricter than the words; check every field a person or the brain wrote."""
    fields = ("name", "question", "positive_label", "negative_label", "target_question", "locate", "alert_message", "summary")
    joined = " · ".join(str(spec.get(k) or "") for k in fields)
    return check_text(joined)


POLICY_PROMPT = """Safety policy (enforced): Vigil watches objects, events and conditions, never kinds of people.
Refuse (policy.allowed = false) any request that would: identify, recognize or follow a particular person; single
out people by gender, race, ethnicity, religion, age, disability, pregnancy, sexual orientation or appearance; look at
bodies, nudity or attractiveness; watch bathrooms, changing rooms, bedrooms or other people's homes; monitor people
covertly; guess emotions, intentions, health or social status; single out children; or anything unlawful.
Allowed: any person or object doing something concrete (entering, falling, missing a hard hat, waiting in line),
objects, vehicles, animals, states of things. When refusing, give a one-sentence reason and a neutral rewording."""
