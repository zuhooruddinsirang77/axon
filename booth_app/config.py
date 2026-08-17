"""
Central configuration: layout, colors, fonts, multilingual strings, and
asset filenames for the Axon Interactive AI Booth.
"""
import os

import theme

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1920, 1080
FPS = 60

# Near-black, slightly-cool base — matches the mascot/building renders
# (glossy white subject, neon ring glow, true-black backdrop) so the booth
# reads as one brand instead of a generic dark-UI template.
BG_COLOR = (7, 8, 13)             # #07080D
BG_COLOR_TOP = (6, 7, 12)
BG_COLOR_BOTTOM = (14, 10, 22)
TEXT_COLOR = (255, 255, 255)
ACCENT_COLOR = (0, 220, 255)
ACCENT_COLOR_2 = (170, 90, 255)
ACCENT_GREEN = (110, 255, 175)
ACCENT_BLUE = (80, 120, 255)
# The mascot's signature eye-visor sweep: green -> cyan -> blue -> purple.
# Reused everywhere an accent needs more than one flat color (rings,
# dividers, badges, wheel slices, corner frame) so every screen feels like
# the same object family.
BRAND_GRADIENT = [ACCENT_GREEN, ACCENT_COLOR, ACCENT_BLUE, ACCENT_COLOR_2]
DIM_TEXT_COLOR = (150, 160, 180)
CARD_BORDER_COLOR = (58, 66, 92)
CARD_BORDER_HIGHLIGHT = (0, 220, 255)
CARD_FILL = (17, 20, 33)
CARD_FILL_ALT = (22, 19, 38)

FONT_NAME = "Segoe UI, Arial"
# Segoe UI has no Devanagari glyphs (renders Hindi as tofu boxes), and while
# it does carry Arabic glyphs, cursive joining/RTL order still needs to be
# pre-shaped (see text_render.py) before any font can display it correctly.
# Nirmala UI is Windows' bundled Devanagari-complete font.
FONT_NAME_BY_LANG = {
    "ar": "Segoe UI, Tahoma, Arial",
    "ur": "Segoe UI, Tahoma, Arial",
    "hi": "Nirmala UI, Segoe UI",
}
# Sized for a large event display viewed from several feet away, not a
# desktop monitor — meaningfully bigger than default UI type scales.
FONT_TITLE_SIZE = 64
FONT_SUBTITLE_SIZE = 32
FONT_CARD_SIZE = 30
FONT_BANNER_SIZE = 46
FONT_SMALL_SIZE = 23
FONT_WORDMARK_SIZE = 34

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

# ---------------------------------------------------------------------------
# Asset filenames (must match files in assets/ exactly)
# ---------------------------------------------------------------------------
ASSET_AXON_MISCHIEVOUS = "Axon Mischievous.png"
ASSET_AXON_WAVING = "Axon Waving.png"
ASSET_AXON_THINKING = "Axon Thinking.png"
ASSET_AXON_JUMPING = "Axon Jumping.png"
ASSET_AXON_RETAIL = "Axon Retail.png"
ASSET_AXON_IT = "Acox IT Professional.png"
ASSET_AXON_WAREHOUSE = "Axon Warehouse.png"
ASSET_AXON_DOCTOR = "Axon Doctor.png"
ASSET_AXON_FINANCE = "Axon Finance.png"

ASSET_HOSPITAL = "Hospital.png"
ASSET_FINANCIAL = "Financial Building.png"
ASSET_RETAIL = "Retail Shop.png"
ASSET_IT_CENTER = "IT Data Center.png"
ASSET_ENERGY = "Energy Building.png"
ASSET_WAREHOUSE = "Warehouse and Logistics.png"

# ---------------------------------------------------------------------------
# Building grid (State 4A) — 3 cols x 2 rows, centered under the header/title
# ---------------------------------------------------------------------------
CARD_SIZE = (500, 300)
GRID_START = (170, 250)
GRID_GAP = (540, 340)

BUILDINGS = [
    {
        "key": "healthcare",
        "name": "Healthcare",
        "img": ASSET_HOSPITAL,
        "reveal_img": ASSET_AXON_DOCTOR,
    },
    {
        "key": "finance",
        "name": "Finance",
        "img": ASSET_FINANCIAL,
        "reveal_img": ASSET_AXON_FINANCE,
    },
    {
        "key": "retail",
        "name": "Retail",
        "img": ASSET_RETAIL,
        "reveal_img": ASSET_AXON_RETAIL,
    },
    {
        "key": "it",
        "name": "IT Data Center",
        "img": ASSET_IT_CENTER,
        "reveal_img": ASSET_AXON_IT,
    },
    {
        "key": "energy",
        "name": "Energy",
        "img": ASSET_ENERGY,
        "reveal_img": ASSET_AXON_THINKING,
    },
    {
        "key": "logistics",
        "name": "Logistics",
        "img": ASSET_WAREHOUSE,
        "reveal_img": ASSET_AXON_WAREHOUSE,
    },
]

MASCOT_OVERLAY_SIZE = (320, 320)
MASCOT_IDLE_POS = (WIDTH // 2 - 200, HEIGHT - 300)
REVEAL_COSTUME_SIZE = (240, 240)

# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------
LANGUAGES = [
    {"code": "en", "label": "English", "keywords": ["english", "1"]},
    {"code": "ur", "label": "Urdu", "keywords": ["urdu", "اردو", "2"]},
    {"code": "hi", "label": "Hindi", "keywords": ["hindi", "हिंदी", "3"]},
    {"code": "ar", "label": "Arabic", "keywords": ["arabic", "عربي", "4"]},
    {"code": "fr", "label": "French", "keywords": ["french", "français", "francais", "5"]},
]
DEFAULT_LANGUAGE = "en"

# ---------------------------------------------------------------------------
# Multilingual strings
# ---------------------------------------------------------------------------
STRINGS = {
    "en": {
        "idle_banner": "Step up to interact with Axon!",
        "welcome": "Hey there! I'm Axon. Welcome to our booth. Step up to test our AI!",
        "lang_prompt": "Which language do you speak?",
        "game_menu_prompt": "Say 1 for Hiding Game, 2 for Myth Quiz, or 3 for the Swag Wheel!",
        "game_menu_title": "Select Your AI Challenge",
        "hiding_prompt": "Pick a number from 1 to 6 to guess which building I'm hiding in!",
        "hiding_title": "Guess Which Industry Axon is Hiding In!",
        "hiding_reveal_title": "SURPRISE! AXON SERVES ALL INDUSTRIES!",
        "reveal_pitch": "Surprise! We are hiding behind ALL industries because our AI powers every sector. Speak to our team right here to learn more!",
        "myth_question": "True or False: AI can reduce logistics routing costs by over 30%?",
        "myth_true_reaction": "That's TRUE! AI-driven routing can cut logistics costs dramatically.",
        "myth_false_reaction": "Actually, that's TRUE — AI-driven routing really can cut costs that much!",
        "wheel_prompt": "Shout 'SPIN THE WHEEL' into the mic to claim your prize!",
        "wheel_title": "Spin the Swag Wheel!",
        "handoff_banner": "TALK TO OUR HUMAN TEAM RIGHT HERE!",
        "handoff_audio": "Turn around and speak to our representatives right here to get started!",
    },
    "ur": {
        "idle_banner": "ایکسن کے ساتھ بات چیت کے لیے آگے آئیں!",
        "welcome": "ہیلو! میں ایکسن ہوں۔ ہمارے بوتھ میں خوش آمدید۔",
        "lang_prompt": "آپ کون سی زبان بولتے ہیں؟",
        "game_menu_prompt": "چھپنے کے کھیل کے لیے 1، خرافات کوئز کے لیے 2، یا انعامی پہیے کے لیے 3 کہیں!",
        "game_menu_title": "اپنا AI چیلنج منتخب کریں",
        "hiding_prompt": "1 سے 6 تک کوئی نمبر چنیں!",
        "hiding_title": "اندازہ لگائیں ایکسن کہاں چھپا ہے!",
        "hiding_reveal_title": "سرپرائز! ہم ہر صنعت میں موجود ہیں!",
        "reveal_pitch": "سرپرائز! ہم تمام صنعتوں کے پیچھے ہیں کیونکہ ہمارا AI ہر شعبے کو طاقت دیتا ہے۔",
        "myth_question": "درست یا غلط: AI لاجسٹکس روٹنگ لاگت میں 30% سے زیادہ کمی لا سکتا ہے؟",
        "myth_true_reaction": "درست! AI روٹنگ لاگت میں نمایاں کمی لا سکتا ہے۔",
        "myth_false_reaction": "دراصل، یہ درست ہے!",
        "wheel_prompt": "انعام کے لیے مائیک میں 'اسپن دی ویل' بولیں!",
        "wheel_title": "انعامی پہیہ گھمائیں!",
        "handoff_banner": "ہماری ٹیم سے یہاں بات کریں!",
        "handoff_audio": "شروع کرنے کے لیے مڑیں اور ہمارے نمائندوں سے بات کریں۔",
    },
    "hi": {
        "idle_banner": "एक्सन से बातचीत के लिए आगे आएं!",
        "welcome": "नमस्ते! मैं एक्सन हूं। हमारे बूथ में आपका स्वागत है।",
        "lang_prompt": "आप कौन सी भाषा बोलते हैं?",
        "game_menu_prompt": "छिपने के खेल के लिए 1, मिथक क्विज़ के लिए 2, या इनाम व्हील के लिए 3 कहें!",
        "game_menu_title": "अपनी AI चुनौती चुनें",
        "hiding_prompt": "1 से 6 तक कोई नंबर चुनें!",
        "hiding_title": "अंदाज़ा लगाएं एक्सन कहाँ छिपा है!",
        "hiding_reveal_title": "सरप्राइज! हम हर उद्योग में हैं!",
        "reveal_pitch": "सरप्राइज! हम सभी उद्योगों के पीछे छिपे हैं क्योंकि हमारा AI हर क्षेत्र को सशक्त बनाता है।",
        "myth_question": "सही या गलत: AI लॉजिस्टिक्स रूटिंग लागत को 30% से अधिक घटा सकता है?",
        "myth_true_reaction": "सही! AI रूटिंग लागत को नाटकीय रूप से घटा सकता है।",
        "myth_false_reaction": "असल में, यह सही है!",
        "wheel_prompt": "इनाम पाने के लिए माइक में 'स्पिन द व्हील' बोलें!",
        "wheel_title": "इनाम व्हील घुमाएं!",
        "handoff_banner": "हमारी टीम से यहीं बात करें!",
        "handoff_audio": "शुरू करने के लिए मुड़ें और हमारे प्रतिनिधियों से बात करें।",
    },
    "ar": {
        "idle_banner": "تقدم للتفاعل مع أكسون!",
        "welcome": "مرحباً! أنا أكسون. أهلاً بك في جناحنا.",
        "lang_prompt": "ما هي اللغة التي تتحدثها؟",
        "game_menu_prompt": "قل 1 للعبة الاختباء، 2 لمسابقة الحقائق، أو 3 لعجلة الجوائز!",
        "game_menu_title": "اختر تحدي الذكاء الاصطناعي الخاص بك",
        "hiding_prompt": "اختر رقماً من 1 إلى 6!",
        "hiding_title": "خمن أين يختبئ أكسون!",
        "hiding_reveal_title": "مفاجأة! نحن في كل الصناعات!",
        "reveal_pitch": "مفاجأة! نحن نختبئ وراء جميع الصناعات لأن الذكاء الاصطناعي لدينا يخدم كل القطاعات.",
        "myth_question": "صح أم خطأ: يمكن للذكاء الاصطناعي خفض تكاليف التوجيه اللوجستي بأكثر من 30%؟",
        "myth_true_reaction": "صحيح! يمكن للتوجيه المعتمد على الذكاء الاصطناعي خفض التكاليف بشكل كبير.",
        "myth_false_reaction": "في الواقع هذا صحيح!",
        "wheel_prompt": "اصرخ 'أدر العجلة' في الميكروفون للحصول على جائزتك!",
        "wheel_title": "أدر عجلة الجوائز!",
        "handoff_banner": "تحدث مع فريقنا هنا مباشرة!",
        "handoff_audio": "استدر وتحدث مع ممثلينا هنا للبدء.",
    },
    "fr": {
        "idle_banner": "Approchez-vous pour interagir avec Axon !",
        "welcome": "Salut ! Je suis Axon. Bienvenue à notre stand !",
        "lang_prompt": "Quelle langue parlez-vous ?",
        "game_menu_prompt": "Dites 1 pour le jeu de cache-cache, 2 pour le quiz, ou 3 pour la roue !",
        "game_menu_title": "Choisissez votre défi IA",
        "hiding_prompt": "Choisissez un chiffre de 1 à 6 !",
        "hiding_title": "Devinez où se cache Axon !",
        "hiding_reveal_title": "SURPRISE ! AXON EST PARTOUT !",
        "reveal_pitch": "Surprise ! Nous sommes cachés derrière TOUTES les industries car notre IA alimente tous les secteurs.",
        "myth_question": "Vrai ou faux : l'IA peut réduire les coûts logistiques de plus de 30% ?",
        "myth_true_reaction": "Vrai ! Le routage par IA peut réduire les coûts de façon spectaculaire.",
        "myth_false_reaction": "En fait, c'est vrai !",
        "wheel_prompt": "Criez 'TOURNE LA ROUE' dans le micro pour votre prix !",
        "wheel_title": "Tournez la roue des cadeaux !",
        "handoff_banner": "PARLEZ À NOTRE ÉQUIPE ICI MÊME !",
        "handoff_audio": "Retournez-vous et parlez à nos représentants pour commencer !",
    },
}

def t(lang_code, key):
    """Look up a localized string, falling back to English then the key itself."""
    return STRINGS.get(lang_code, STRINGS[DEFAULT_LANGUAGE]).get(
        key, STRINGS[DEFAULT_LANGUAGE].get(key, key)
    )

# ---------------------------------------------------------------------------
# Swag wheel prizes (procedurally drawn, no image asset)
# ---------------------------------------------------------------------------
WHEEL_PRIZES = [
    "Free T-Shirt",
    "AI Consult",
    "Sticker Pack",
    "20% Off Demo",
    "Water Bottle",
    "Coffee Voucher",
    "Notebook",
    "Grand Prize",
]
# Sampled along the brand gradient end-to-end, NOT looped (looping back
# from purple to green would cut through a muddy grey midpoint — purple
# and green aren't adjacent on the RGB wheel) — so the wheel, the biggest,
# most eye-catching graphic in the app, stays unmistakably "Axon" instead
# of a generic carnival wheel.
WHEEL_COLORS = [theme.brand_color(i / 7, BRAND_GRADIENT, loop=False) for i in range(8)]

# ---------------------------------------------------------------------------
# Timing (seconds)
# ---------------------------------------------------------------------------
FACE_DETECT_HOLD_TIME = 1.5
HANDOFF_TIMEOUT = 5.0
WHEEL_SPIN_DURATION = 4.0

# ---------------------------------------------------------------------------
# OpenAI / ElevenLabs system prompt (for STT/TTS service wiring)
# ---------------------------------------------------------------------------
WHISPER_MODEL = "whisper-1"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
