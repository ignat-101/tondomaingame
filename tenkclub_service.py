from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


TEN_K_CONFIG_URL = "https://10kclub.com/api/clubs/10k/config"
INDEX_PATH = Path(__file__).resolve().parent / "tenkclub-index.json"


@dataclass
class DomainAbility:
    key: str
    name: str
    description: str
    trigger: str
    cooldown: int
    cost: int
    probability: float
    charges: int
    once_per_battle: bool
    power: int


@dataclass
class DomainRankData:
    domain: str
    normalizedNumber: str
    score: int
    tierLabel: str
    rarityLabel: str
    atomicPatterns: list[str]
    superPattern: str | None
    traitFlags: list[str]
    passiveAbility: dict[str, Any]
    activeAbility: dict[str, Any]
    role: str
    className: str
    level: int
    experience: int
    visualStyle: str
    badgeColor: str
    frameVariant: str
    holoEffect: str
    shortLore: str
    dataSource: str
    specialCollections: list[str]
    tierId: str
    bonusScore: int
    baseScore: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["class"] = payload.pop("className")
        return payload


ROLE_OPTIONS = [
    "Tank",
    "Damage",
    "Control",
    "Support",
    "Trickster",
    "Guardian",
    "Fortune",
    "Combo",
    "Disruptor",
    "Sniper",
]

CLASS_COUNTERS = {
    "Tank": ["Pierce", "True Damage"],
    "Damage": ["Block", "Disrupt"],
    "Control": ["Tempo", "Stability"],
    "Support": ["Burst", "Silence"],
    "Trickster": ["Discipline", "Stability"],
    "Guardian": ["Pierce", "Combo"],
    "Fortune": ["Stability", "Control"],
    "Combo": ["Disrupt", "Guard"],
    "Disruptor": ["Guard", "Support"],
    "Sniper": ["Tank", "Reflect"],
}


_CONFIG_CACHE: dict[str, Any] = {"config": None}
_INDEX_CACHE: dict[str, Any] = {"data": None}


def normalize_domain_number(domain: str) -> str | None:
    text = str(domain or "").strip().lower()
    if text.endswith(".ton"):
        text = text[:-4]
    if len(text) == 4 and text.isdigit():
        return text
    return None


def fetch_10k_config(http: requests.Session | None = None, force_refresh: bool = False) -> dict[str, Any]:
    if _CONFIG_CACHE["config"] is not None and not force_refresh:
        return _CONFIG_CACHE["config"]
    session = http or requests.Session()
    response = session.get(TEN_K_CONFIG_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    config = payload.get("config") or {}
    _CONFIG_CACHE["config"] = config
    return config


def _match_mask(mask: str, number: str) -> tuple[bool, dict[str, str]]:
    if len(mask) != len(number):
        return False, {}
    bindings: dict[str, str] = {}
    for digit, token in zip(number, mask):
        if token.isdigit():
            if digit != token:
                return False, {}
            continue
        bound = bindings.get(token)
        if bound is None:
            bindings[token] = digit
        elif bound != digit:
            return False, {}
    if len(set(bindings.values())) != len(bindings):
        return False, {}
    return True, bindings


def _calendar_date_match(number: str, formats: list[str]) -> bool:
    value = number.zfill(4)
    for fmt in formats:
        if fmt == "MMDD":
            month = int(value[:2])
            day = int(value[2:])
        elif fmt == "DDMM":
            day = int(value[:2])
            month = int(value[2:])
        else:
            continue
        if month < 1 or month > 12:
            continue
        if 1 <= day <= calendar.monthrange(2024, month)[1]:
            return True
    return False


def _eval_rule_condition(condition: dict[str, Any], number: str, matched_patterns: set[str], matched_groups: set[str]) -> bool:
    ctype = (condition or {}).get("type")
    if not ctype:
        return False
    if ctype == "mask":
        ok, bindings = _match_mask((condition.get("mask") or "").strip(), number)
        if not ok:
            return False
        for item in condition.get("constraints") or []:
            if item.get("operator") != "adjacent":
                continue
            left = bindings.get(item.get("left"))
            right = bindings.get(item.get("right"))
            if left is None or right is None or abs(int(left) - int(right)) != 1:
                return False
        return True
    if ctype == "numeric-range":
        value = int(number)
        return int(condition.get("min", 0)) <= value <= int(condition.get("max", 9999))
    if ctype == "arithmetic-sequence":
        digits = [int(ch) for ch in number]
        diffs = [digits[i + 1] - digits[i] for i in range(len(digits) - 1)]
        return any(all(diff == int(step) for diff in diffs) for step in (condition.get("steps") or []))
    if ctype == "calendar-date":
        return _calendar_date_match(number, condition.get("formats") or ["MMDD", "DDMM"])
    if ctype == "palindrome":
        return number == number[::-1]
    if ctype == "all-of":
        return all(_eval_rule_condition(sub, number, matched_patterns, matched_groups) for sub in (condition.get("conditions") or []))
    if ctype == "any-of":
        return any(_eval_rule_condition(sub, number, matched_patterns, matched_groups) for sub in (condition.get("conditions") or []))
    if ctype == "pattern-ref":
        return any(ref in matched_patterns for ref in (condition.get("anyOf") or []))
    if ctype == "group-ref":
        required = condition.get("requiredGroups") or []
        min_matched = int(condition.get("minMatchedPatterns", 0))
        return all(group_id in matched_groups for group_id in required) and len(matched_patterns) >= min_matched
    return False


def fetch10kClubMetadata(domainNumber: str, http: requests.Session | None = None) -> dict[str, Any]:
    number = normalize_domain_number(domainNumber)
    if number is None:
        raise ValueError("Expected four-digit domain number")
    config = fetch_10k_config(http=http)
    patterns_by_id = {item["id"]: item for item in (config.get("patterns") or []) if item.get("id")}
    groups_by_id = {item["id"]: item for item in (config.get("groups") or []) if item.get("id")}
    pattern_rules = sorted(config.get("patternRules") or [], key=lambda item: int(item.get("priority", 0)))
    group_rules = sorted(config.get("groupRules") or [], key=lambda item: int(item.get("priority", 0)))

    matched_pattern_ids: set[str] = set()
    for rule in pattern_rules:
        if _eval_rule_condition(rule.get("condition") or {}, number, matched_pattern_ids, set()):
            pattern_id = rule.get("patternId")
            if pattern_id:
                matched_pattern_ids.add(pattern_id)

    matched_group_ids: set[str] = set()
    for rule in group_rules:
        if _eval_rule_condition(rule.get("condition") or {}, number, matched_pattern_ids, matched_group_ids):
            group_id = rule.get("groupId")
            if group_id:
                matched_group_ids.add(group_id)

    if not any(group_id in matched_group_ids for group_id in ("tier0", "tier1", "tier2")):
        matched_group_ids.add("regular")
    if any(group_id.startswith("g-") for group_id in matched_group_ids):
        matched_group_ids.add("special")

    tier_group_id = "regular"
    for candidate in ("tier0", "tier1", "tier2", "regular"):
        if candidate in matched_group_ids:
            tier_group_id = candidate
            break
    tier_group = groups_by_id.get(tier_group_id) or {}

    base_score = max(
        [int((groups_by_id.get(group_id) or {}).get("scoreValue") or 0) for group_id in matched_group_ids if (groups_by_id.get(group_id) or {}).get("scoreMode") == "base"]
        or [2500]
    )
    bonus_score = sum(
        int((groups_by_id.get(group_id) or {}).get("scoreValue") or 0)
        for group_id in matched_group_ids
        if (groups_by_id.get(group_id) or {}).get("scoreMode") == "bonus"
    )

    atomic_patterns = [
        (patterns_by_id[pattern_id].get("labelRu") or patterns_by_id[pattern_id].get("label") or pattern_id)
        for pattern_id in sorted(matched_pattern_ids)
        if pattern_id in patterns_by_id
    ]
    special_collections = [
        (groups_by_id[group_id].get("labelRu") or groups_by_id[group_id].get("label") or group_id)
        for group_id in sorted(matched_group_ids)
        if group_id.startswith("g-") and group_id in groups_by_id
    ]
    return {
        "tier": tier_group.get("label") or tier_group_id,
        "tierRu": tier_group.get("labelRu") or tier_group.get("label") or tier_group_id,
        "tierId": tier_group_id,
        "score": int(base_score + bonus_score),
        "baseScore": int(base_score),
        "bonusScore": int(bonus_score),
        "patterns": atomic_patterns,
        "patternIds": sorted(matched_pattern_ids),
        "groups": sorted(matched_group_ids),
        "specialCollections": special_collections,
        "dataSource": "10kclub-config",
    }


def _fallback_patterns(number: str) -> tuple[list[str], str | None, list[str]]:
    flags: list[str] = []
    patterns: list[str] = []
    digits = [int(ch) for ch in number]
    counts = {ch: number.count(ch) for ch in set(number)}
    unique_count = len(counts)
    if unique_count == 1:
        patterns.append("Все цифры одинаковые")
        flags.append("quad-repeat")
    if sorted(counts.values(), reverse=True)[:1] == [3]:
        patterns.append("Тройка")
        flags.append("triple")
    if sorted(counts.values()) == [2, 2]:
        patterns.append("Две пары")
        flags.append("double-pair")
    if number == number[::-1]:
        patterns.append("Палиндром")
        flags.append("palindrome")
    if number[:2] == number[2:][::-1]:
        patterns.append("Почти палиндром")
        flags.append("near-palindrome")
    diffs = [digits[i + 1] - digits[i] for i in range(3)]
    if all(diff == 1 for diff in diffs) or all(diff == -1 for diff in diffs):
        patterns.append("Последовательность")
        flags.append("sequence")
    if number[0] == number[2] and number[1] == number[3] and number[0] != number[1]:
        patterns.append("Чередование")
        flags.append("alternating")
    if "8" in number:
        patterns.append("Содержит 8")
        flags.append("has-eight")
    if "0" in number:
        patterns.append("Содержит 0")
        flags.append("has-zero")
    repeat_blocks = {"1212", "6969", "1001", "4554"}
    if number in repeat_blocks:
        patterns.append(f"Блок {number}")
        flags.append(f"block-{number}")
    super_pattern = patterns[0] if patterns else None
    return patterns, super_pattern, flags


def _rarity_label(tier_id: str, score: int, special_count: int) -> str:
    if tier_id == "tier0" or score >= 100000:
        return "Legendary"
    if tier_id == "tier1" or score >= 25000:
        return "Epic"
    if tier_id == "tier2" or score >= 10000:
        return "Rare"
    if special_count >= 2 or score >= 6000:
        return "Uncommon"
    return "Common"


def _hash_pick(seed: str, items: list[str]) -> str:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return items[int(digest[:8], 16) % len(items)]


def _derive_role_class(number: str, patterns: list[str], score: int, tier_id: str) -> tuple[str, str]:
    signal = " ".join(patterns).lower()
    if "зерк" in signal or "палиндром" in signal:
        role = "Control"
    elif "ступ" in signal or "последователь" in signal:
        role = "Combo"
    elif "0" in number:
        role = "Guardian"
    elif "8" in number:
        role = "Fortune"
    elif tier_id == "tier0":
        role = "Sniper"
    elif tier_id == "tier1":
        role = "Damage"
    else:
        role = _hash_pick(f"role:{number}:{score}", ROLE_OPTIONS)
    class_name = {
        "Tank": "Bulwark",
        "Damage": "Executioner",
        "Control": "Cipher",
        "Support": "Signal",
        "Trickster": "Mirage",
        "Guardian": "Aegis",
        "Fortune": "Lucky Star",
        "Combo": "Sequence",
        "Disruptor": "Breaker",
        "Sniper": "Focus",
    }[role]
    return role, class_name


def _ability_name(prefix: str, number: str, role: str) -> str:
    return f"{prefix} {number[-2:]} {role}"


def _build_abilities(number: str, role: str, rarity: str, score: int, patterns: list[str], tier_id: str) -> tuple[DomainAbility, DomainAbility]:
    rarity_bonus = {"Common": 0, "Uncommon": 1, "Rare": 2, "Epic": 3, "Legendary": 4}[rarity]
    passive_power = min(4, 1 + rarity_bonus)
    active_power = min(6, 2 + rarity_bonus)
    passive_proc = min(1.0, 0.22 + rarity_bonus * 0.12)
    active_proc = min(1.0, 0.72 + rarity_bonus * 0.06)
    active_charges = 1 + (1 if rarity in {"Epic", "Legendary"} else 0)
    passive_charges = 2 + (1 if rarity in {"Rare", "Epic", "Legendary"} else 0)
    active_cooldown = 3 if rarity == "Common" else (2 if rarity in {"Uncommon", "Rare"} else 1)
    if tier_id == "tier0":
        active_proc = min(1.0, active_proc + 0.08)
        passive_proc = min(1.0, passive_proc + 0.08)
        active_charges += 1
    elif tier_id == "tier1":
        active_proc = min(1.0, active_proc + 0.04)
        passive_proc = min(1.0, passive_proc + 0.05)
    elif tier_id == "tier2":
        passive_proc = min(1.0, passive_proc + 0.03)
    if role in {"Tank", "Guardian"}:
        passive = DomainAbility("bulwark_passive", _ability_name("Bulwark", number, role), "Получает щит в начале первого проигранного раунда.", "on_round_loss", 2, 0, max(passive_proc, 0.72), 1, False, passive_power)
        active = DomainAbility("fortify_active", _ability_name("Fortify", number, role), "Усиливает блок и режет входящий урон в этом раунде.", "manual", active_cooldown, 3, max(active_proc, 0.86), active_charges, False, active_power)
    elif role in {"Damage", "Sniper"}:
        passive = DomainAbility("focus_passive", _ability_name("Focus", number, role), "Немного повышает шанс крита после успешного блока.", "after_guard_win", 2, 0, max(passive_proc, 0.48), passive_charges, False, passive_power)
        active = DomainAbility("pierce_active", _ability_name("Pierce", number, role), "Следующий натиск частично игнорирует защиту.", "manual", active_cooldown, 3, active_proc, active_charges, False, active_power)
    elif role in {"Control", "Disruptor", "Trickster"}:
        passive = DomainAbility("jam_passive", _ability_name("Jam", number, role), "Редко снижает силу вражеской активной способности.", "on_enemy_ability", 3, 0, max(passive_proc - 0.08, 0.35), passive_charges, False, passive_power)
        active = DomainAbility("disrupt_active", _ability_name("Disrupt", number, role), "Ломает темп соперника и режет его энергию в раунде.", "manual", active_cooldown + 1, 3, max(active_proc - 0.06, 0.74), active_charges, False, active_power)
    elif role in {"Fortune", "Support"}:
        passive = DomainAbility("lucky_passive", _ability_name("Luck", number, role), "Иногда добавляет небольшой бонус к диапазону урона.", "on_attack_roll", 1, 0, max(passive_proc - 0.06, 0.28), 99, False, passive_power)
        active = DomainAbility("surge_active", _ability_name("Surge", number, role), "Даёт дополнительную энергию и усиливает следующий выбор.", "manual", max(1, active_cooldown - 1), 3, max(active_proc - 0.04, 0.78), active_charges, False, active_power)
    else:
        passive = DomainAbility("combo_passive", _ability_name("Combo", number, role), "После победы в раунде слегка усиливает следующий ход.", "on_round_win", 2, 0, max(passive_proc, 0.62), passive_charges, False, passive_power)
        active = DomainAbility("sequence_active", _ability_name("Sequence", number, role), "Усиливает натиск, если до этого был блок.", "manual", active_cooldown, 3, max(active_proc, 0.82), active_charges, False, active_power)
    return passive, active


def _visuals(number: str, rarity: str, patterns: list[str], tier_id: str) -> tuple[str, str, str, str]:
    signal = " ".join(patterns).lower()
    if tier_id == "tier0":
        return "obsidian-gold", "#f6c453", "crown", "solar"
    if tier_id == "tier1":
        return "ember-black", "#ff8a4c", "royal", "ember"
    if tier_id == "tier2":
        return "neon-blue", "#43b8ff", "precision", "glacier"
    if "зерк" in signal or "палиндром" in signal:
        return "mirror-violet", "#b9b2ff", "mirror", "prism"
    if "ступ" in signal or "последователь" in signal:
        return "signal-pink", "#f39bff", "sequence", "pulse"
    return "navy-grid", "#7f8a9d", "plain", "soft"


def _lore(number: str, role: str, rarity: str, super_pattern: str | None) -> str:
    if super_pattern:
        return f"{number}.ton закреплён как {super_pattern.lower()} и играет от роли {role.lower()}."
    return f"{number}.ton держится на роли {role.lower()} и выигрывает за счёт точных решений, а не голой редкости."


def build_domain_rank_data(domain: str, source: dict[str, Any] | None = None, *, level: int = 1, experience: int = 0) -> DomainRankData:
    number = normalize_domain_number(domain)
    if number is None:
        raise ValueError("Expected 4-digit .ton domain")
    if source is None:
        try:
            source = fetch10kClubMetadata(number)
        except Exception:
            patterns, super_pattern, flags = _fallback_patterns(number)
            score = 2500 + len(patterns) * 400
            tier_id = "regular"
            tier = "Regular"
            rarity = _rarity_label(tier_id, score, 0)
            role, class_name = _derive_role_class(number, patterns, score, tier_id)
            passive, active = _build_abilities(number, role, rarity, score, patterns, tier_id)
            visual, badge, frame, holo = _visuals(number, rarity, patterns, tier_id)
            return DomainRankData(
                domain=f"{number}.ton",
                normalizedNumber=number,
                score=score,
                tierLabel=tier,
                rarityLabel=rarity,
                atomicPatterns=patterns,
                superPattern=super_pattern,
                traitFlags=flags,
                passiveAbility=asdict(passive),
                activeAbility=asdict(active),
                role=role,
                className=class_name,
                level=level,
                experience=experience,
                visualStyle=visual,
                badgeColor=badge,
                frameVariant=frame,
                holoEffect=holo,
                shortLore=_lore(number, role, rarity, super_pattern),
                dataSource="fallback",
                specialCollections=[],
                tierId=tier_id,
                bonusScore=max(0, score - 2500),
                baseScore=2500,
            )

    atomic_patterns = list(source.get("patterns") or [])
    super_pattern = (source.get("specialCollections") or atomic_patterns or [None])[0]
    flags = []
    if number == number[::-1]:
        flags.append("palindrome")
    if "0" in number:
        flags.append("has-zero")
    if "8" in number:
        flags.append("has-eight")
    if len(set(number)) <= 2:
        flags.append("low-entropy")
    if len(set(int(ch) % 2 for ch in number)) == 1:
        flags.append("parity-uniform")
    rarity = _rarity_label(source.get("tierId") or "regular", int(source.get("score") or 2500), len(source.get("specialCollections") or []))
    role, class_name = _derive_role_class(number, atomic_patterns + list(source.get("specialCollections") or []), int(source.get("score") or 2500), source.get("tierId") or "regular")
    passive, active = _build_abilities(number, role, rarity, int(source.get("score") or 2500), atomic_patterns, source.get("tierId") or "regular")
    visual, badge, frame, holo = _visuals(number, rarity, atomic_patterns + list(source.get("specialCollections") or []), source.get("tierId") or "regular")
    return DomainRankData(
        domain=f"{number}.ton",
        normalizedNumber=number,
        score=int(source.get("score") or 2500),
        tierLabel=source.get("tierRu") or source.get("tier") or "Regular",
        rarityLabel=rarity,
        atomicPatterns=atomic_patterns,
        superPattern=super_pattern,
        traitFlags=flags,
        passiveAbility=asdict(passive),
        activeAbility=asdict(active),
        role=role,
        className=class_name,
        level=level,
        experience=experience,
        visualStyle=visual,
        badgeColor=badge,
        frameVariant=frame,
        holoEffect=holo,
        shortLore=_lore(number, role, rarity, super_pattern),
        dataSource=source.get("dataSource") or "10kclub-config",
        specialCollections=list(source.get("specialCollections") or []),
        tierId=source.get("tierId") or "regular",
        bonusScore=int(source.get("bonusScore") or 0),
        baseScore=int(source.get("baseScore") or 2500),
    )


def load_index(index_path: Path | None = None) -> dict[str, Any]:
    path = index_path or INDEX_PATH
    if _INDEX_CACHE["data"] is not None:
        return _INDEX_CACHE["data"]
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        _INDEX_CACHE["data"] = data
        return data
    return {}


def getDomainMetadata(domain: str, *, http: requests.Session | None = None, index_path: Path | None = None, progress: dict[str, int] | None = None) -> dict[str, Any]:
    number = normalize_domain_number(domain)
    if number is None:
        raise ValueError("Expected 4-digit .ton domain")
    progress = progress or {}
    index = load_index(index_path=index_path)
    cached = index.get(number)
    if isinstance(cached, dict):
        source = dict(cached)
        source["dataSource"] = "tenkclub-index"
        data = build_domain_rank_data(number, source, level=int(progress.get("level", 1)), experience=int(progress.get("experience", 0)))
        return data.to_dict()
    try:
        source = fetch10kClubMetadata(number, http=http)
        data = build_domain_rank_data(number, source, level=int(progress.get("level", 1)), experience=int(progress.get("experience", 0)))
        return data.to_dict()
    except Exception:
        data = build_domain_rank_data(number, None, level=int(progress.get("level", 1)), experience=int(progress.get("experience", 0)))
        return data.to_dict()


def explainDomainUniqueness(domain: str, *, http: requests.Session | None = None, index_path: Path | None = None, progress: dict[str, int] | None = None) -> dict[str, Any]:
    meta = getDomainMetadata(domain, http=http, index_path=index_path, progress=progress)
    return {
        "domain": meta["domain"],
        "tier": meta["tierLabel"],
        "rarity": meta["rarityLabel"],
        "score": meta["score"],
        "patterns": meta["atomicPatterns"],
        "superPattern": meta["superPattern"],
        "specialCollections": meta.get("specialCollections", []),
        "role": meta["role"],
        "class": meta["class"],
        "passiveAbility": meta["passiveAbility"],
        "activeAbility": meta["activeAbility"],
        "why": [
            f"Tier: {meta['tierLabel']} ({meta['tierId']})",
            f"Score: {meta['score']} = base {meta['baseScore']} + bonus {meta['bonusScore']}",
            f"Atomic patterns: {', '.join(meta['atomicPatterns']) if meta['atomicPatterns'] else 'none'}",
            f"Special collections: {', '.join(meta.get('specialCollections', [])) if meta.get('specialCollections') else 'none'}",
            f"Assigned role/class: {meta['role']} / {meta['class']}",
            f"Passive: {meta['passiveAbility']['name']}",
            f"Active: {meta['activeAbility']['name']}",
        ],
        "dataSource": meta["dataSource"],
    }


def build10kIndex(output_path: str | Path | None = None, *, http: requests.Session | None = None) -> Path:
    path = Path(output_path) if output_path else INDEX_PATH
    payload: dict[str, Any] = {}
    for value in range(10000):
        number = f"{value:04d}"
        source = fetch10kClubMetadata(number, http=http)
        payload[number] = source
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _INDEX_CACHE["data"] = payload
    return path
