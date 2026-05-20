from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from time import time

import requests

from app.core.models import SpeciesOccurrence, SpeciesPreset, SpeciesProfile

GBIF_OCCURRENCE_URL = "https://api.gbif.org/v1/occurrence/search"
OBIS_OCCURRENCE_URL = "https://api.obis.org/v3/occurrence"
CACHE_DIR = Path("data/cache/species")


AFRICA_SPECIES = [
    ("lion", "非洲狮", "Panthera leo", "易危", 55),
    ("african_savanna_elephant", "非洲草原象", "Loxodonta africana", "濒危", 70),
    ("african_forest_elephant", "非洲森林象", "Loxodonta cyclotis", "极危", 90),
    ("giraffe", "长颈鹿", "Giraffa camelopardalis", "易危", 55),
    ("masai_giraffe", "马赛长颈鹿", "Giraffa tippelskirchi", "濒危", 70),
    ("reticulated_giraffe", "网纹长颈鹿", "Giraffa reticulata", "濒危", 70),
    ("plains_zebra", "平原斑马", "Equus quagga", "近危", 35),
    ("grevy_zebra", "细纹斑马", "Equus grevyi", "濒危", 70),
    ("mountain_zebra", "山斑马", "Equus zebra", "易危", 55),
    ("white_rhino", "白犀牛", "Ceratotherium simum", "近危", 45),
    ("black_rhino", "黑犀牛", "Diceros bicornis", "极危", 90),
    ("hippopotamus", "河马", "Hippopotamus amphibius", "易危", 55),
    ("pygmy_hippo", "倭河马", "Choeropsis liberiensis", "濒危", 70),
    ("cheetah", "猎豹", "Acinonyx jubatus", "易危", 55),
    ("leopard", "花豹", "Panthera pardus", "易危", 55),
    ("african_wild_dog", "非洲野犬", "Lycaon pictus", "濒危", 70),
    ("spotted_hyena", "斑鬣狗", "Crocuta crocuta", "低关注", 20),
    ("brown_hyena", "棕鬣狗", "Parahyaena brunnea", "近危", 35),
    ("aardvark", "土豚", "Orycteropus afer", "低关注", 20),
    ("meerkat", "狐獴", "Suricata suricatta", "低关注", 20),
    ("warthog", "疣猪", "Phacochoerus africanus", "低关注", 20),
    ("giant_pangolin", "大穿山甲", "Smutsia gigantea", "濒危", 70),
    ("ground_pangolin", "南非穿山甲", "Smutsia temminckii", "易危", 55),
    ("chimpanzee", "黑猩猩", "Pan troglodytes", "濒危", 70),
    ("bonobo", "倭黑猩猩", "Pan paniscus", "濒危", 70),
    ("western_gorilla", "西部大猩猩", "Gorilla gorilla", "极危", 90),
    ("eastern_gorilla", "东部大猩猩", "Gorilla beringei", "极危", 90),
    ("olive_baboon", "橄榄狒狒", "Papio anubis", "低关注", 20),
    ("gelada", "狮尾狒", "Theropithecus gelada", "低关注", 20),
    ("vervet_monkey", "青猴", "Chlorocebus pygerythrus", "低关注", 20),
    ("african_buffalo", "非洲水牛", "Syncerus caffer", "近危", 35),
    ("common_eland", "大羚羊", "Taurotragus oryx", "低关注", 20),
    ("greater_kudu", "大捻角羚", "Tragelaphus strepsiceros", "低关注", 20),
    ("nyala", "林羚", "Tragelaphus angasii", "低关注", 20),
    ("sable_antelope", "马羚", "Hippotragus niger", "低关注", 20),
    ("roan_antelope", "马羚羊", "Hippotragus equinus", "低关注", 20),
    ("oryx", "南非剑羚", "Oryx gazella", "低关注", 20),
    ("addax", "弯角剑羚", "Addax nasomaculatus", "极危", 90),
    ("springbok", "跳羚", "Antidorcas marsupialis", "低关注", 20),
    ("impala", "黑斑羚", "Aepyceros melampus", "低关注", 20),
    ("thomson_gazelle", "汤氏瞪羚", "Eudorcas thomsonii", "低关注", 20),
    ("grant_gazelle", "格氏瞪羚", "Nanger granti", "低关注", 20),
    ("wildebeest", "角马", "Connochaetes taurinus", "低关注", 20),
    ("topi", "转角牛羚", "Damaliscus lunatus", "低关注", 20),
    ("red_hartebeest", "红狷羚", "Alcelaphus buselaphus", "低关注", 20),
    ("waterbuck", "水羚", "Kobus ellipsiprymnus", "低关注", 20),
    ("lechwe", "水泽羚", "Kobus leche", "近危", 35),
    ("sitatunga", "薮羚", "Tragelaphus spekii", "低关注", 20),
    ("okapi", "霍加狓", "Okapia johnstoni", "濒危", 70),
    ("ostrich", "鸵鸟", "Struthio camelus", "低关注", 20),
    ("shoebill", "鲸头鹳", "Balaeniceps rex", "易危", 55),
    ("grey_crowned_crane", "灰冠鹤", "Balearica regulorum", "濒危", 70),
    ("secretarybird", "蛇鹫", "Sagittarius serpentarius", "濒危", 70),
    ("martial_eagle", "猛雕", "Polemaetus bellicosus", "濒危", 70),
    ("african_fish_eagle", "非洲海雕", "Icthyophaga vocifer", "低关注", 20),
    ("marabou_stork", "秃鹳", "Leptoptilos crumenifer", "低关注", 20),
    ("saddle_billed_stork", "鞍嘴鹳", "Ephippiorhynchus senegalensis", "低关注", 20),
    ("greater_flamingo", "大红鹳", "Phoenicopterus roseus", "低关注", 20),
    ("lesser_flamingo", "小红鹳", "Phoeniconaias minor", "近危", 35),
    ("nile_crocodile", "尼罗鳄", "Crocodylus niloticus", "低关注", 20),
    ("dwarf_crocodile", "侏鳄", "Osteolaemus tetraspis", "易危", 55),
    ("nile_monitor", "尼罗巨蜥", "Varanus niloticus", "低关注", 20),
    ("african_rock_python", "非洲岩蟒", "Python sebae", "低关注", 20),
    ("leopard_tortoise", "豹纹陆龟", "Stigmochelys pardalis", "低关注", 20),
]

MARINE_SPECIES = [
    ("common_dolphin", "普通海豚", "Delphinus delphis", "低关注", 20),
    ("bottlenose_dolphin", "宽吻海豚", "Tursiops truncatus", "低关注", 20),
    ("spinner_dolphin", "飞旋海豚", "Stenella longirostris", "低关注", 20),
    ("spotted_dolphin", "大西洋斑海豚", "Stenella frontalis", "低关注", 20),
    ("orca", "虎鲸", "Orcinus orca", "数据不足", 30),
    ("humpback_whale", "座头鲸", "Megaptera novaeangliae", "低关注", 25),
    ("blue_whale", "蓝鲸", "Balaenoptera musculus", "濒危", 70),
    ("fin_whale", "长须鲸", "Balaenoptera physalus", "易危", 55),
    ("sei_whale", "塞鲸", "Balaenoptera borealis", "濒危", 70),
    ("minke_whale", "小须鲸", "Balaenoptera acutorostrata", "低关注", 20),
    ("gray_whale", "灰鲸", "Eschrichtius robustus", "低关注", 25),
    ("sperm_whale", "抹香鲸", "Physeter macrocephalus", "易危", 55),
    ("beluga", "白鲸", "Delphinapterus leucas", "低关注", 20),
    ("narwhal", "独角鲸", "Monodon monoceros", "低关注", 25),
    ("dugong", "儒艮", "Dugong dugon", "易危", 55),
    ("west_indian_manatee", "西印度海牛", "Trichechus manatus", "易危", 55),
    ("green_turtle", "绿海龟", "Chelonia mydas", "濒危", 70),
    ("hawksbill_turtle", "玳瑁", "Eretmochelys imbricata", "极危", 90),
    ("loggerhead_turtle", "蠵龟", "Caretta caretta", "易危", 55),
    ("leatherback_turtle", "棱皮龟", "Dermochelys coriacea", "易危", 55),
    ("olive_ridley_turtle", "丽龟", "Lepidochelys olivacea", "易危", 55),
    ("kemps_ridley_turtle", "肯氏丽龟", "Lepidochelys kempii", "极危", 90),
    ("great_white_shark", "大白鲨", "Carcharodon carcharias", "易危", 55),
    ("whale_shark", "鲸鲨", "Rhincodon typus", "濒危", 70),
    ("basking_shark", "姥鲨", "Cetorhinus maximus", "濒危", 70),
    ("tiger_shark", "鼬鲨", "Galeocerdo cuvier", "近危", 35),
    ("bull_shark", "公牛鲨", "Carcharhinus leucas", "易危", 55),
    ("hammerhead_shark", "双髻鲨", "Sphyrna lewini", "极危", 90),
    ("oceanic_whitetip", "远洋白鳍鲨", "Carcharhinus longimanus", "极危", 90),
    ("blue_shark", "大青鲨", "Prionace glauca", "近危", 35),
    ("manta_ray", "前口蝠鲼", "Mobula birostris", "濒危", 70),
    ("reef_manta", "礁蝠鲼", "Mobula alfredi", "易危", 55),
    ("spotted_eagle_ray", "斑点鹰魟", "Aetobatus narinari", "濒危", 70),
    ("yellowfin_tuna", "黄鳍金枪鱼", "Thunnus albacares", "近危", 35),
    ("bluefin_tuna", "大西洋蓝鳍金枪鱼", "Thunnus thynnus", "近危", 35),
    ("bigeye_tuna", "大眼金枪鱼", "Thunnus obesus", "易危", 55),
    ("skipjack_tuna", "鲣鱼", "Katsuwonus pelamis", "低关注", 20),
    ("albacore", "长鳍金枪鱼", "Thunnus alalunga", "低关注", 20),
    ("swordfish", "剑鱼", "Xiphias gladius", "低关注", 20),
    ("sailfish", "旗鱼", "Istiophorus platypterus", "低关注", 20),
    ("mahi_mahi", "鲯鳅", "Coryphaena hippurus", "低关注", 20),
    ("atlantic_cod", "大西洋鳕", "Gadus morhua", "易危", 55),
    ("atlantic_salmon", "大西洋鲑", "Salmo salar", "近危", 35),
    ("european_eel", "欧洲鳗鲡", "Anguilla anguilla", "极危", 90),
    ("american_eel", "美洲鳗鲡", "Anguilla rostrata", "濒危", 70),
    ("ocean_sunfish", "翻车鲀", "Mola mola", "易危", 55),
    ("clownfish", "小丑鱼", "Amphiprion ocellaris", "低关注", 20),
    ("mandarinfish", "青蛙鱼", "Synchiropus splendidus", "低关注", 20),
    ("lionfish", "狮子鱼", "Pterois volitans", "低关注", 20),
    ("coelacanth", "矛尾鱼", "Latimeria chalumnae", "极危", 90),
    ("giant_clam", "大砗磲", "Tridacna gigas", "易危", 55),
    ("queen_conch", "女王凤凰螺", "Aliger gigas", "濒危", 70),
    ("horseshoe_crab", "美洲鲎", "Limulus polyphemus", "易危", 55),
    ("japanese_horseshoe_crab", "日本鲎", "Tachypleus tridentatus", "濒危", 70),
    ("krill", "南极磷虾", "Euphausia superba", "低关注", 20),
    ("common_octopus", "普通章鱼", "Octopus vulgaris", "低关注", 20),
    ("giant_pacific_octopus", "北太平洋巨型章鱼", "Enteroctopus dofleini", "低关注", 20),
    ("chambered_nautilus", "鹦鹉螺", "Nautilus pompilius", "易危", 55),
    ("staghorn_coral", "鹿角珊瑚", "Acropora cervicornis", "极危", 90),
    ("elkhorn_coral", "麋角珊瑚", "Acropora palmata", "极危", 90),
    ("great_star_coral", "巨星珊瑚", "Montastraea cavernosa", "低关注", 20),
    ("brain_coral", "脑珊瑚", "Diploria labyrinthiformis", "低关注", 20),
    ("sea_fan", "海扇", "Gorgonia ventalina", "低关注", 20),
    ("posidonia", "海神草", "Posidonia oceanica", "低关注", 20),
    ("sugar_kelp", "糖海带", "Saccharina latissima", "低关注", 20),
    ("giant_kelp", "巨藻", "Macrocystis pyrifera", "低关注", 20),
]


def _preset(
    key: str,
    chinese_name: str,
    scientific_name: str,
    group: str,
    source: str,
    region: str,
    conservation_status: str,
    conservation_prior_score: float,
) -> SpeciesPreset:
    return SpeciesPreset(
        key=key,
        chinese_name=chinese_name,
        scientific_name=scientific_name,
        group=group,
        source=source,
        region=region,
        conservation_status=conservation_status,
        conservation_prior_score=conservation_prior_score,
    )


SPECIES_PRESETS = [
    *[_preset(key, chinese, scientific, "非洲动物", "gbif", "africa", status, prior) for key, chinese, scientific, status, prior in AFRICA_SPECIES],
    *[_preset(key, chinese, scientific, "海洋生物", "obis", "ocean", status, prior) for key, chinese, scientific, status, prior in MARINE_SPECIES],
]


def list_species_presets() -> list[SpeciesPreset]:
    return SPECIES_PRESETS


def build_species_profile(
    scientific_name: str,
    source: str = "gbif",
    region: str = "africa",
    limit: int = 240,
) -> SpeciesProfile:
    limit = max(20, min(limit, 300))
    source = source.lower()
    region = region.lower()
    preset = _find_preset(scientific_name, source, region)

    if source == "obis":
        occurrences, total_records = _load_obis_occurrences(scientific_name, limit)
    else:
        occurrences, total_records = _load_gbif_occurrences(scientific_name, region, limit)

    years = [item.year for item in occurrences if item.year]
    countries = Counter(item.country for item in occurrences if item.country)
    recent_year = max(years) if years else None
    country_count = len(countries)
    occurrence_density_score = _density_score(total_records)
    recency_score = _recency_score(recent_year)
    data_quality_score = round(min(1.0, len(occurrences) / max(1, limit)) * 100, 1)
    conservation_prior = preset.conservation_prior_score if preset else 40.0
    conservation_status = preset.conservation_status if preset else "未知"
    species_risk_score = round(
        conservation_prior * 0.45
        + (100 - occurrence_density_score) * 0.25
        + (100 - recency_score) * 0.20
        + (100 - data_quality_score) * 0.10,
        1,
    )

    return SpeciesProfile(
        scientific_name=scientific_name,
        chinese_name=preset.chinese_name if preset else None,
        source=source.upper(),
        region=_display_region(region),
        total_records=total_records,
        sample_size=len(occurrences),
        recent_year=recent_year,
        country_count=country_count,
        top_countries=[{"country": name, "count": count} for name, count in countries.most_common(6)],
        conservation_status=conservation_status,
        conservation_prior_score=conservation_prior,
        occurrence_density_score=occurrence_density_score,
        recency_score=recency_score,
        data_quality_score=data_quality_score,
        species_risk_score=species_risk_score,
        risk_label=_species_risk_label(species_risk_score),
        notes=_species_notes(source, region, total_records, len(occurrences), recent_year),
        occurrences=occurrences,
    )


def _load_gbif_occurrences(scientific_name: str, region: str, limit: int) -> tuple[list[SpeciesOccurrence], int]:
    params = {
        "scientificName": scientific_name,
        "hasCoordinate": "true",
        "limit": limit,
    }
    if region == "africa":
        params["continent"] = "AFRICA"
    payload = _read_json_cache(_cache_filename("gbif", scientific_name, region, limit), GBIF_OCCURRENCE_URL, params, ttl_seconds=24 * 3600)
    occurrences = [_gbif_occurrence(row) for row in payload.get("results", [])]
    return [item for item in occurrences if item is not None], int(payload.get("count", 0))


def _load_obis_occurrences(scientific_name: str, limit: int) -> tuple[list[SpeciesOccurrence], int]:
    params = {
        "scientificname": scientific_name,
        "size": limit,
    }
    payload = _read_json_cache(_cache_filename("obis", scientific_name, "ocean", limit), OBIS_OCCURRENCE_URL, params, ttl_seconds=24 * 3600)
    occurrences = [_obis_occurrence(row) for row in payload.get("results", [])]
    return [item for item in occurrences if item is not None], int(payload.get("total", 0))


def _gbif_occurrence(row: dict) -> SpeciesOccurrence | None:
    lat = row.get("decimalLatitude")
    lon = row.get("decimalLongitude")
    if lat is None or lon is None:
        return None
    return SpeciesOccurrence(
        source="GBIF",
        scientific_name=row.get("species") or row.get("scientificName") or "",
        common_name=None,
        latitude=float(lat),
        longitude=float(lon),
        event_date=_short_date(row.get("eventDate")),
        year=_safe_int(row.get("year")),
        country=row.get("country"),
        locality=row.get("stateProvince") or row.get("locality") or row.get("verbatimLocality"),
        dataset=row.get("datasetName"),
        basis_of_record=row.get("basisOfRecord"),
    )


def _obis_occurrence(row: dict) -> SpeciesOccurrence | None:
    lat = row.get("decimalLatitude")
    lon = row.get("decimalLongitude")
    if lat is None or lon is None:
        return None
    return SpeciesOccurrence(
        source="OBIS",
        scientific_name=row.get("species") or row.get("scientificName") or "",
        common_name=row.get("vernacularName"),
        latitude=float(lat),
        longitude=float(lon),
        event_date=_short_date(row.get("eventDate")),
        year=_safe_int(row.get("date_year") or row.get("year")),
        country=row.get("country") or row.get("waterBody"),
        locality=row.get("waterBody") or row.get("locality"),
        dataset=row.get("datasetName"),
        basis_of_record=row.get("basisOfRecord"),
    )


def _find_preset(scientific_name: str, source: str, region: str) -> SpeciesPreset | None:
    for preset in SPECIES_PRESETS:
        if preset.scientific_name.lower() == scientific_name.lower() and preset.source == source and preset.region == region:
            return preset
    return None


def _display_region(region: str) -> str:
    return {"africa": "非洲", "ocean": "全球海洋"}.get(region, region)


def _density_score(total_records: int) -> float:
    if total_records <= 0:
        return 0.0
    score = min(100.0, 18.0 * (len(str(total_records)) - 1) + min(28.0, total_records / 300.0))
    return round(score, 1)


def _recency_score(recent_year: int | None) -> float:
    if recent_year is None:
        return 0.0
    years_old = max(0, date.today().year - recent_year)
    return round(max(0.0, 100.0 - years_old * 12.5), 1)


def _species_risk_label(score: float) -> str:
    if score >= 70:
        return "高关注"
    if score >= 45:
        return "中等关注"
    return "低关注"


def _species_notes(source: str, region: str, total_records: int, sample_size: int, recent_year: int | None) -> list[str]:
    notes = [
        f"当前样本来自 {source.upper()}，本地缓存24小时，适合研究展示和探索性分析。",
        "物种关注分由内置保护状态先验、记录密度、最近观测年份和样本质量构建，不等同于 IUCN 濒危等级。",
    ]
    if region == "africa":
        notes.append("非洲动物记录使用 GBIF 的非洲大陆过滤，坐标可能因保护敏感物种而被模糊化。")
    if source == "obis":
        notes.append("海洋生物记录来自 OBIS，部分数据点可能包含船测、搁浅、观测或历史采样记录。")
    if total_records == 0 or sample_size == 0:
        notes.append("当前查询没有拿到可用坐标点，可以换用学名或提高查询范围。")
    elif recent_year and date.today().year - recent_year > 5:
        notes.append("最近样本年份偏旧，后续应结合遥感或保护状态数据交叉验证。")
    return notes


def _short_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:10] if text else None


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _cache_filename(source: str, scientific_name: str, region: str, limit: int) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", scientific_name.strip().lower()).strip("_")
    return f"{source}_{safe_name}_{region}_{limit}.json"


def _read_json_cache(filename: str, url: str, params: dict, ttl_seconds: int) -> dict:
    path = _cache_path(filename)
    if path.exists() and time() - path.stat().st_mtime < ttl_seconds:
        return json.loads(path.read_text(encoding="utf-8"))
    response = requests.get(url, params=params, timeout=35)
    response.raise_for_status()
    payload = response.json()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _cache_path(filename: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / filename
