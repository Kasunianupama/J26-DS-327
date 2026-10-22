"""Sinhala/Tamil factual answer templates; evidence values and provenance remain unchanged."""
import re
from math import isfinite

def choose(language,si,ta):return si if language=='si' else ta
def number(value,language,digits=0):
    if value is None:return choose(language,'ලබා දී නැත','வழங்கப்படவில்லை')
    if not isfinite(float(value)):raise ValueError('Non-finite evidence')
    return f'{value:,.{digits}f}'

WARNINGS={
'Observational model-input what-if only; not a causal effect, guaranteed benefit or management recommendation.': ('නිරීක්ෂණ දත්ත මත ආකෘති ආදාන වෙනසක් පමණි. හේතුමය බලපෑමක්, සහතික ප්\u200dරතිලාභයක් හෝ කළමනාකරණ නිර්දේශයක් නොවේ.', 'இது கண்காணிப்புத் தரவு சார்ந்த மாதிரி உள்ளீட்டு மாற்றம் மட்டுமே. காரண விளைவோ உறுதியான பயனோ மேலாண்மைப் பரிந்துரையோ அல்ல.'),
'Costs, welfare and operational feasibility have not been validated.': ('වියදම්, සත්ව සුභසාධනය සහ මෙහෙයුම් හැකියාව තහවුරු කර නැත.', 'செலவு, விலங்கு நலன் மற்றும் செயல்படுத்தும் சாத்தியம் சரிபார்க்கப்படவில்லை.'),
'Source core version and an uncertainty interval are not supplied by C2; compatibility with other component outputs is unverified.': ('C2 මූලාශ්\u200dර core අනුවාදයක් හෝ අවිනිශ්චිතතා පරාසයක් ලබා දෙන්නේ නැත. වෙනත් සංරචක ප්\u200dරතිඵල සමඟ ගැළපීම තහවුරු නැත.', 'C2 மூல core பதிப்பையோ நிச்சயமின்மை இடைவெளியையோ வழங்கவில்லை. மற்ற கூறுகளின் வெளியீடுகளுடன் பொருத்தம் சரிபார்க்கப்படவில்லை.'),
'The baseline uses the latest usable recorded cow-day, not necessarily current conditions.': ('මූලික තත්ත්වය අවසන් භාවිත කළ හැකි වාර්තාගත ගව දිනය භාවිතා කරයි. එය වත්මන් තත්ත්වය බව තහවුරු නොවේ.', 'அடிப்படை கடைசிப் பயன்படக்கூடிய பதிவான பசு நாளைப் பயன்படுத்துகிறது. அது தற்போதைய நிலைமையாக இருக்க வேண்டியதில்லை.'),
'C3 withheld the what-if estimate because its training support could not be checked.': ('පුහුණු පරාසය පරීක්ෂා කළ නොහැකි නිසා C3 අනුකරණ ඇස්තමේන්තුව පෙන්වන්නේ නැත.', 'பயிற்சி வரம்பைச் சரிபார்க்க முடியாததால் C3 மாற்று மதிப்பீட்டைக் காட்டவில்லை.'),
'No compatible Farm X model artifact is installed; yield estimates are unavailable.': ('ගැළපෙන Farm X ආකෘති ගොනුවක් ස්ථාපනය කර නැත. කිරි ඇස්තමේන්තු නොමැත.', 'பொருந்தும் Farm X மாதிரிக் கோப்பு நிறுவப்படவில்லை. பால் மதிப்பீடுகள் கிடைக்கவில்லை.'),
'No evaluated Farm X milk-yield model artifact is installed.': ('ඇගයූ Farm X කිරි ආකෘති ගොනුවක් ස්ථාපනය කර නැත.', 'மதிப்பீடு செய்யப்பட்ட Farm X பால் மாதிரிக் கோப்பு நிறுவப்படவில்லை.'),
'The model artifact requires a different scikit-learn version.': ('ආකෘති ගොනුවට වෙනත් scikit-learn අනුවාදයක් අවශ්\u200dයය.', 'மாதிரிக் கோப்பிற்கு வேறு scikit-learn பதிப்பு தேவை.'),
'This is a model-input perturbation, not a verified causal intervention effect.': ('මෙය ආකෘති ආදාන වෙනසකි. තහවුරු කළ හේතුමය මැදිහත්වීමේ බලපෑමක් නොවේ.', 'இது மாதிரி உள்ளீட்டு மாற்றம். சரிபார்க்கப்பட்ட காரணத் தலையீட்டு விளைவல்ல.'),
'A predicted difference may not occur in the real world.': ('පුරෝකථන වෙනස සැබෑ තත්ත්වයේ සිදු නොවිය හැක.', 'முன்னறிவிக்கப்பட்ட வேறுபாடு உண்மையில் நிகழாமல் இருக்கலாம்.'),
'Changing THI represents an exposure what-if; it does not model a cooling action.': ('THI වෙනස නිරාවරණය වෙනස් කිරීමක් පමණි. සිසිලන ක්\u200dරියාවක් ආකෘතිගත නොකරයි.', 'THI மாற்றம் வெளிப்பாட்டு மாற்றத்தை மட்டுமே குறிக்கிறது. குளிர்விப்பு நடவடிக்கையை மாதிரியாக்கவில்லை.'),
'Labor, equipment, cost, welfare, and operational feasibility are not assessed by this simulator.': ('මෙම අනුකාරකය ශ්\u200dරමය, උපකරණ, වියදම්, සුභසාධනය හෝ මෙහෙයුම් හැකියාව ඇගයීම නොකරයි.', 'இந்த உருவகப்படுத்தி உழைப்பு, உபகரணம், செலவு, நலன் அல்லது செயல்படுத்தும் சாத்தியத்தை மதிப்பிடவில்லை.'),
'The baseline model prediction is unavailable; no counterfactual estimate was returned.': ('මූලික ආකෘති පුරෝකථනය නොමැති නිසා විකල්ප ඇස්තමේන්තුවක් ලබා දී නැත.', 'அடிப்படை மாதிரி முன்னறிவிப்பு இல்லாததால் மாற்று மதிப்பீடு வழங்கப்படவில்லை.'),
'This is a combined model-input perturbation, not a verified causal intervention effect.': ('මෙය ඒකාබද්ධ ආකෘති ආදාන වෙනසකි. තහවුරු කළ හේතුමය බලපෑමක් නොවේ.', 'இது இணைந்த மாதிரி உள்ளீட்டு மாற்றம். சரிபார்க்கப்பட்ட காரண விளைவல்ல.'),
'The result is not calculated by adding individual scenario differences.': ('ප්\u200dරතිඵලය තනි තත්ත්ව වෙනස්කම් එකතු කර ගණනය කර නැත.', 'தனி மாற்று வேறுபாடுகளைக் கூட்டி இந்த முடிவு கணக்கிடப்படவில்லை.'),
'Farm operational feasibility has not been validated.': ('ගොවිපළේ මෙහෙයුම් හැකියාව තහවුරු කර නැත.', 'பண்ணையில் செயல்படுத்தும் சாத்தியம் சரிபார்க்கப்படவில்லை.'),
'The THI value is an exposure what-if, not a specified cooling action.': ('THI අගය නිරාවරණ විකල්පයකි. නියමිත සිසිලන ක්\u200dරියාවක් නොවේ.', 'THI மதிப்பு வெளிப்பாட்டு மாற்றம் மட்டுமே. குறிப்பிட்ட குளிர்விப்பு நடவடிக்கையல்ல.'),
'Development model; source-data compatibility must be established before combining local records.':('සංවර්ධන ආකෘතියකි. දේශීය වාර්තා සමඟ ඒකාබද්ධ කිරීමට පෙර මූලාශ්‍ර දත්ත ගැළපීම තහවුරු කළ යුතුය.','இது உருவாக்க நிலையில் உள்ள மாதிரி. உள்ளூர் பதிவுகளுடன் இணைக்கும் முன் மூலத் தரவின் பொருத்தத்தை உறுதிப்படுத்த வேண்டும்.'),
'Forecast bounds are incomplete; no range was invented.':('පුරෝකථන සීමා අසම්පූර්ණය. අලුත් පරාසයක් නිර්මාණය කර නැත.','முன்னறிவிப்பின் வரம்புகள் முழுமையாக இல்லை. புதிய வரம்பு உருவாக்கப்படவில்லை.'),
'Point forecast is outside its supplied bounds; producer review is needed.':('පුරෝකථන අගය ලබා දුන් සීමාවලින් පිටතය. නිෂ්පාදකයාගේ සමාලෝචනය අවශ්‍යය.','முன்னறிவிப்பு மதிப்பு வழங்கப்பட்ட வரம்புகளுக்கு வெளியே உள்ளது. தயாரிப்பாளரின் மீளாய்வு தேவை.'),
'Historical experimental research assessment; not a current alert, validated forecast or confirmed cause.':('මෙය අතීත පර්යේෂණ ඇගයීමකි. වත්මන් අනතුරු ඇඟවීමක්, තහවුරු කළ පුරෝකථනයක් හෝ සනාථ කළ හේතුවක් නොවේ.','இது கடந்தகால பரிசோதனை ஆய்வு மதிப்பீடு. தற்போதைய எச்சரிக்கையோ, சரிபார்க்கப்பட்ட முன்னறிவிப்போ, உறுதிப்படுத்தப்பட்ட காரணமோ அல்ல.'),
'Producer marks this output as research only.':('නිෂ්පාදකයා මෙම ප්‍රතිඵලය පර්යේෂණ සඳහා පමණක් ලෙස සලකුණු කර ඇත.','தயாரிப்பாளர் இந்த வெளியீட்டை ஆய்வுக்காக மட்டுமே எனக் குறித்துள்ளார்.'),
'Producer explicitly disallows live warnings.':('නිෂ්පාදකයා සජීවී අනතුරු ඇඟවීම් සඳහා අවසර දී නැත.','நேரடி எச்சரிக்கைகளுக்கு தயாரிப்பாளர் அனுமதி வழங்கவில்லை.'),
'Source core version is not supplied; compatibility with local core is unverified.':('මූලාශ්‍ර core අනුවාදය ලබා දී නැත. දේශීය core දත්ත සමඟ ගැළපීම තහවුරු කර නැත.','மூல core பதிப்பு வழங்கப்படவில்லை. உள்ளூர் core தரவுடன் பொருத்தம் சரிபார்க்கப்படவில்லை.'),
'Assessment date is not proof the result was available then; retain generation and cutoff timestamps.':('ඇගයීම් දිනයෙන් එම දිනයේ ප්‍රතිඵලය තිබූ බව තහවුරු නොවේ. නිර්මාණය කළ වේලාව සහ දත්ත සීමා වේලාව සලකා බලන්න.','மதிப்பீட்டுத் தேதி அன்று முடிவு கிடைத்ததற்கான சான்றல்ல. உருவாக்கிய நேரத்தையும் தரவு முடிவு நேரத்தையும் கவனிக்கவும்.'),
'Score units and category thresholds are not confirmed; do not assign an independent risk category.':('ලකුණු ඒකක සහ කාණ්ඩ සීමා තහවුරු කර නැත. වෙනම අවදානම් කාණ්ඩයක් පවරා නැත.','மதிப்பெண் அலகுகளும் வகைப்பாட்டு வரம்புகளும் உறுதிப்படுத்தப்படவில்லை. தனியாக அபாய வகை ஒதுக்கப்படவில்லை.'),
'Combined score is missing; no replacement was calculated.':('ඒකාබද්ධ ලකුණ ලබා දී නැත. ආදේශක අගයක් ගණනය කර නැත.','ஒருங்கிணைந்த மதிப்பெண் இல்லை. மாற்று மதிப்பு கணக்கிடப்படவில்லை.'),
'Assessment cutoff is not supplied in the export.':('ඇගයීම සඳහා දත්ත සීමා වේලාව ලබා දී නැත.','மதிப்பீட்டின் தரவு முடிவு நேரம் வழங்கப்படவில்லை.'),
'Weather coverage is incomplete for the latest seven-day period.':('අවසන් දින හතේ කාලගුණ දත්ත ආවරණය අසම්පූර්ණය.','கடைசி ஏழு நாட்களுக்கான வானிலைத் தரவு முழுமையாக இல்லை.'),
}

def translate_warning(text,language):
    if text in WARNINGS:return WARNINGS[text][0 if language=='si' else 1]
    match=re.fullmatch(r'Historical records end on (.+); these are not current farm conditions\.',text)
    if match:return choose(language,f'අතීත වාර්තා {match[1]} දිනෙන් අවසන් වේ. මේවා වත්මන් ගොවිපළ තත්ත්වයන් නොවේ.',f'கடந்தகால பதிவுகள் {match[1]} அன்று முடிகின்றன. இவை தற்போதைய பண்ணை நிலைமைகள் அல்ல.')
    match=re.fullmatch(r'(\d+) months fail ETL herd-balance acceptance; herd counts are reconstructed and require review\.',text)
    if match:return choose(language,f'මාස {match[1]} ක ETL රංචු ශේෂ පරීක්ෂණ අසමත්ය. නැවත ගොඩනැගූ සත්ව ගණන් සමාලෝචනය කළ යුතුය.',f'{match[1]} மாதங்களில் ETL மந்தை இருப்புச் சோதனை தோல்வியடைந்தது. மீள்கட்டமைக்கப்பட்ட எண்ணிக்கைகள் மீளாய்வு செய்யப்பட வேண்டும்.')
    if text.startswith(('delpro:','shipments:')):
        source='DelPro' if text.startswith('delpro:') else choose(language,'නැව්ගත කිරීම්','விநியோகப் பதிவுகள்')
        return choose(language,f'{source}: දත්ත ආවරණය, හිඩැස් හෝ ධන ආරම්භක අගයක් නොමැති නිසා සතිපතා වෙනස ගණනය කළ නොහැක.',f'{source}: தரவு முழுமை, இடைவெளிகள் அல்லது நேர்மறையான தொடக்க மதிப்பு இல்லாமையால் வாராந்திர மாற்றத்தைக் கணக்கிட முடியாது.')
    return choose(language,'අමතර මූලාශ්‍ර සීමාව: ','கூடுதல் மூல வரம்பு: ')+text

TITLES={
'Considering a change':('වෙනසක් සලකා බැලීම','ஒரு மாற்றத்தைப் பரிசீலித்தல்'),
'Recorded herd summary':('වාර්තාගත රංචු සාරාංශය','பதிவுசெய்யப்பட்ட மந்தைச் சுருக்கம்'),
'Recorded milk comparison':('වාර්තාගත කිරි සංසන්දනය','பதிவுசெய்யப்பட்ட பால் ஒப்பீடு'),
'Historical weather':('අතීත කාලගුණය','கடந்தகால வானிலை'),
'Stored forecast':('ගබඩා කළ පුරෝකථනය','சேமிக்கப்பட்ட முன்னறிவிப்பு'),
'Historical risk assessment':('අතීත අවදානම් ඇගයීම','கடந்தகால அபாய மதிப்பீடு'),
'What-if simulation':('විකල්ප තත්ත්ව අනුකරණය','மாற்றுச் சூழல் உருவகப்படுத்தல்'),
}

def status_answer(reply,language):
    text=reply['answer'];context=reply.get('context',{});missing=reply.get('missing_fields',[])
    if reply.get('interpretation_failure'):
        failure = reply['interpretation_failure']
        messages = {
            'timeout': ('දේශීය භාෂා ආකෘතියට මෙම ප්‍රශ්නය තේරුම් ගැනීමට වැඩි කාලයක් ගත විය.', 'உள்ளூர் மொழி மாதிரி இந்தக் கேள்வியைப் புரிந்துகொள்ள அதிக நேரம் எடுத்தது.'),
            'busy': ('දේශීය භාෂා ආකෘතිය වෙනත් ප්‍රශ්නයක් සකසමින් සිටී.', 'உள்ளூர் மொழி மாதிரி மற்றொரு கேள்வியைச் செயலாக்குகிறது.'),
            'model_missing': ('දේශීය භාෂා ආකෘතිය Ollama තුළ ස්ථාපනය කර නැත.', 'உள்ளூர் மொழி மாதிரி Ollama இல் நிறுவப்படவில்லை.'),
        }
        si, ta = messages.get(failure, ('දේශීය භාෂා ආකෘතියට මෙම ප්‍රශ්නය තේරුම් ගැනීමට නොහැකි විය.', 'உள்ளூர் மொழி மாதிரியால் இந்தக் கேள்வியைப் புரிந்துகொள்ள முடியவில்லை.'))
        return choose(language, si, ta) + choose(language,
            ' කෙටි ප්‍රශ්නයක් හෝ යෝජිත ප්‍රශ්නයක් භාවිතා කරන්න. දත්ත මෙවලමක් ක්‍රියාත්මක කර නැත.',
            ' சுருக்கமான கேள்வியையோ பரிந்துரைக்கப்பட்ட கேள்வியையோ பயன்படுத்தவும். தரவுக் கருவி இயக்கப்படவில்லை.')
    if missing:
        if missing[0]=='target_period':return choose(language,'පුරෝකථනය අවශ්‍ය දිනය තෝරන්න හෝ YYYY-MM-DD ලෙස දෙන්න. නවතම අදාළ පුරෝකථනය ස්වයංක්‍රීයව තෝරමි. සතිපතා සහ මාසික දිනය ගබඩා කළ කාල පරාසයට ගැළපිය යුතුය.','முன்னறிவிப்பு தேவைப்படும் தேதியைத் தேர்ந்தெடுக்கவும் அல்லது YYYY-MM-DD வடிவில் தரவும். பொருந்தும் சமீபத்திய முன்னறிவிப்பைத் தானாகத் தேர்ந்தெடுப்பேன். வாராந்திர, மாதாந்திர தேதிகள் சேமிக்கப்பட்ட காலத்துடன் பொருந்த வேண்டும்.')
        if context.get('topic')=='forecast':return choose(language,'කුමන යොමු දිනය භාවිතා කළ යුතුද? එම දිනයේ හෝ ඊට පෙර ආරම්භ වූ පුරෝකථනයක් තෝරා ගනී. YYYY-MM-DD ලෙස පිළිතුරු දෙන්න.','எந்தக் குறிப்புத் தேதியைப் பயன்படுத்த வேண்டும்? அந்தத் தேதியில் அல்லது அதற்கு முன் தொடங்கிய முன்னறிவிப்பைத் தேர்ந்தெடுப்பேன். YYYY-MM-DD வடிவில் பதிலளிக்கவும்.')
        return choose(language,'කුමන අතීත දිනය බැලීමට අවශ්‍යද? YYYY-MM-DD ලෙස පිළිතුරු දෙන්න.','எந்தக் கடந்தகால தேதியைப் பார்க்க வேண்டும்? YYYY-MM-DD வடிவில் பதிலளிக்கவும்.')
    if 'simulator is not connected' in text:return choose(language,'අනුකාරකය තවම සම්බන්ධ කර නැත. එහි හිමිකරු පිළිගත් ආදාන සහ ක්‍රියාත්මක කිරීමේ ගිවිසුම ලබා දිය යුතුය. කිසිදු අනුකරණයක් සිදු කර නැත.','உருவகப்படுத்தி இன்னும் இணைக்கப்படவில்லை. அதன் உரிமையாளர் ஆதரிக்கப்படும் உள்ளீடுகளையும் இயக்க முறையையும் வழங்க வேண்டும். எந்த உருவகப்படுத்தலும் இயக்கப்படவில்லை.')
    if 'current alerts' in text or 'live warnings' in text:return choose(language,'C4 ඇගයීම් අතීත පර්යේෂණ සඳහා පමණි. වත්මන් අනතුරු ඇඟවීම් හෝ සජීවී දැනුම්දීම් සඳහා ඒවා භාවිතා කළ නොහැක.','C4 மதிப்பீடுகள் கடந்தகால ஆய்வுக்காக மட்டுமே. தற்போதைய அல்லது நேரடி எச்சரிக்கைகளுக்கு அவற்றைப் பயன்படுத்த முடியாது.')
    if 'Individual animal' in text:return choose(language,'මෙම සංවාදය රංචු මට්ටමේ සාරාංශ දත්ත පමණක් කියවයි. එක් එක් සතාගේ ඉතිහාසය හෝ අවධානය අවශ්‍ය සතුන්ගේ ලැයිස්තු සම්බන්ධ කර නැත.','இந்த உரையாடல் மந்தை அளவிலான சுருக்கத் தரவை மட்டுமே படிக்கிறது. தனிப்பட்ட விலங்கு வரலாறும் கவனம் தேவைப்படும் பட்டியலும் இணைக்கப்படவில்லை.')
    if 'future question' in text:return choose(language,'වාර්තාගත සාරාංශවලින් අනාගත ප්‍රශ්නයකට පිළිතුරු දිය නොහැක. ගබඩා කළ පුරෝකථනයක් සඳහා යොමු සහ ඉලක්ක දිනයන් දෙන්න. කාලගුණ පුරෝකථන සම්බන්ධ කර නැත.','பதிவுசெய்யப்பட்ட சுருக்கங்கள் எதிர்காலக் கேள்விக்குப் பதிலளிக்க முடியாது. சேமிக்கப்பட்ட முன்னறிவிப்பிற்கு குறிப்பு மற்றும் இலக்குத் தேதிகளை வழங்கவும். வானிலை முன்னறிவிப்பு இணைக்கப்படவில்லை.')
    if 'cause or diagnosis' in text:return choose(language,'මෙම වාර්තා සහ පර්යේෂණ ප්‍රතිඵලවලින් හේතුවක් හෝ රෝග නිර්ණයක් තහවුරු කළ නොහැක. වාර්තාගත සාරාංශයක්, පුරෝකථනයක් හෝ අතීත ඇගයීමක් ඉල්ලන්න.','இந்தப் பதிவுகளும் ஆய்வு முடிவுகளும் காரணத்தையோ நோயறிதலையோ உறுதிப்படுத்த முடியாது. பதிவுச் சுருக்கம், முன்னறிவிப்பு அல்லது கடந்தகால மதிப்பீட்டைக் கேட்கவும்.')
    if 'one farm-data question' in text:return choose(language,'කිරි, රංචුව, කාලගුණය, ගබඩා කළ පුරෝකථන හෝ අතීත අවදානම පිළිබඳ එක් පැහැදිලි ප්‍රශ්නයක් අසන්න. ප්‍රශ්නයේ අදහස ආරක්ෂිතව තීරණය කළ නොහැකි විය.','பால், மந்தை, வானிலை, சேமிக்கப்பட்ட முன்னறிவிப்பு அல்லது கடந்தகால அபாயம் பற்றி ஒரு தெளிவான கேள்வியைக் கேட்கவும். கேள்வியின் நோக்கத்தைப் பாதுகாப்பாகத் தீர்மானிக்க முடியவில்லை.')
    if 'invalid' in text.lower():return choose(language,'දිනය වලංගු නැත. YYYY-MM-DD ආකාරයෙන් නිවැරදි දින දර්ශන දිනයක් දෙන්න.','தேதி செல்லுபடியாகவில்லை. YYYY-MM-DD வடிவில் சரியான நாள்காட்டித் தேதியை வழங்கவும்.')
    if 'differ' in text:return choose(language,'ප්‍රශ්නයේ දිනය සහ තෝරාගත් දිනය වෙනස්ය. කරුණාකර එකම දිනය තෝරන්න.','கேள்வியின் தேதியும் தேர்ந்தெடுத்த தேதியும் வேறுபடுகின்றன. இரண்டையும் பொருந்தச் செய்யவும்.')
    if 'guess which date' in text:return choose(language,'දින එකකට වඩා ඇත. යොමු දිනය සහ පුරෝකථන ඉලක්ක දිනය වෙන වෙනම දින පාලකවලින් තෝරන්න.','ஒன்றுக்கு மேற்பட்ட தேதிகள் உள்ளன. குறிப்பு மற்றும் முன்னறிவிப்பு இலக்குத் தேதிகளைத் தேதி கட்டுப்பாடுகளில் தனித்தனியாகத் தேர்ந்தெடுக்கவும்.')
    if 'latest recorded date' in text:
        day=re.search(r'\d{4}-\d{2}-\d{2}',text)[0]
        return choose(language,f'මෙම සාරාංශ කියවනය දැනට {day} අවසන් වාර්තාගත දිනය පමණක් සහාය දක්වයි. වෙනත් දිනයක් ලබා ගත නොහැක. අවසන් සාරාංශය සඳහා දින පාලක හිස් කරන්න.',f'இந்தச் சுருக்க வாசிப்பான் தற்போது கடைசிப் பதிவுத் தேதியான {day} ஐ மட்டுமே ஆதரிக்கிறது. வேறு தேதியைப் பெற முடியாது. கடைசிச் சுருக்கத்திற்கு தேதி கட்டுப்பாடுகளை அழிக்கவும்.')
    if 'unique validated forecast' in text:return choose(language,'එම දින, කාල පරාසය සහ මිනුම සඳහා තනි තහවුරු කළ පුරෝකථනයක් ලබා ගත නොහැක. ගබඩා දත්ත ආවරණය සහ අවසර පරීක්ෂා කරන්න. ආදේශක අගයක් හෝ වෙනත් ආකෘතියක් භාවිතා කර නැත.','அந்தத் தேதிகள், காலம் மற்றும் அளவிற்கான தனித்த சரிபார்க்கப்பட்ட முன்னறிவிப்பு கிடைக்கவில்லை. சேமித்த தரவு மற்றும் அனுமதிகளைச் சரிபார்க்கவும். மாற்று மதிப்போ வேறு மாதிரியோ பயன்படுத்தப்படவில்லை.')
    return choose(language,'මෙම ඉල්ලීම සඳහා තහවුරු කළ දේශීය දත්ත ලබා ගත නොහැක. දින, දත්ත ආවරණය සහ අවසර පරීක්ෂා කරන්න. අනුමාන පිළිතුරක් හෝ බාහිර සේවාවක් භාවිතා කර නැත.','இந்தக் கோரிக்கைக்கான சரிபார்க்கப்பட்ட உள்ளூர் தரவு கிடைக்கவில்லை. தேதிகள், தரவு மற்றும் அனுமதிகளைச் சரிபார்க்கவும். ஊகப் பதிலோ வெளிச் சேவையோ பயன்படுத்தப்படவில்லை.')

def successful_answer(reply,language):
    e=reply['evidence'];n=lambda value,digits=0:number(value,language,digits)
    if reply.get('tool')=='c1_forecast':
        period={'daily':('දෛනික','தினசரி'),'weekly':('සතිපතා','வாராந்திர'),'monthly':('මාසික','மாதாந்திர')}[e['grain']][0 if language=='si' else 1]
        series={'herd_milk':('රංචු කිරි','மந்தைப் பால்'),'n_herd':('මුළු රංචුව','மொத்த மந்தை'),'milking':('කිරි දෙන සතුන්','கறவை விலங்குகள்'),'calvings':('පැටවුන් බිහිවීම්','கன்று ஈனுதல்'),'dry_offs':('කිරි වේලීම්','கறவை நிறுத்தங்கள்'),'real_abortions':('වාර්තාගත ගබ්සා','பதிவுசெய்த கருச்சிதைவுகள்')}[e['series']][0 if language=='si' else 1]
        unit=choose(language,' ලීටර්',' லிட்டர்') if e['series']=='herd_milk' else ''
        answer=choose(language,f"{e['target_period']} සඳහා ගබඩා කළ {period} {series} පුරෝකථනය {n(e['forecast'],2)}{unit} වේ. පුරෝකථනයේ දිනය {e['origin_date']} ය. ",f"{e['target_period']} க்கான சேமிக்கப்பட்ட {period} {series} முன்னறிவிப்பு {n(e['forecast'],2)}{unit}. முன்னறிவிப்பின் தேதி {e['origin_date']}. ")
        if e.get('lower') is not None and e.get('upper') is not None:answer+=choose(language,f"ලබා දුන් සීමා {n(e['lower'],2)} සිට {n(e['upper'],2)}{unit} දක්වාය. ",f"வழங்கப்பட்ட வரம்புகள் {n(e['lower'],2)} முதல் {n(e['upper'],2)}{unit} வரை. ")
        else:answer+=choose(language,'සීමා අසම්පූර්ණය; අලුත් පරාසයක් නිර්මාණය කර නැත. ','வரம்புகள் முழுமையாக இல்லை; புதிய வரம்பு உருவாக்கப்படவில்லை. ')
        return answer+choose(language,'මෙය ගබඩා කළ පුරෝකථනයකි; නව ධාවනයක් හෝ සහතික කළ ප්‍රතිඵලයක් නොවේ. දේශීය core සමඟ ගැළපීම තහවුරු කර නැත.','இது சேமித்த முன்னறிவிப்பு; புதிய இயக்கமோ உறுதியான முடிவோ அல்ல. உள்ளூர் core உடன் பொருத்தம் சரிபார்க்கப்படவில்லை.')
    if reply.get('tool')=='c4_risk':
        from .risk_explanation import explain_risk
        return explain_risk(e, language)
    if 'herd' in e:
        h=e['herd'];return choose(language,f"{e['observed_date']} දිනට නැවත ගොඩනැගූ රංචුවේ මුළු සතුන් {n(h.get('total_animals'))} කි. කිරි දෙන සතුන් {n(h.get('milking'))} ක් සහ කිරි නොදෙන වියළි සතුන් {n(h.get('dry'))} ක් ඇත. මේවා අතීත නැවත ගොඩනැගූ ගණන් වන අතර වත්මන් ගොවිපළ තත්ත්වයන් නොවේ.",f"{e['observed_date']} நிலவரப்படி மீள்கட்டமைக்கப்பட்ட மந்தையில் மொத்தம் {n(h.get('total_animals'))} விலங்குகள் உள்ளன. கறவை விலங்குகள் {n(h.get('milking'))}; உலர் விலங்குகள் {n(h.get('dry'))}. இவை கடந்தகால மீள்கட்டமைக்கப்பட்ட எண்ணிக்கைகள்; தற்போதைய பண்ணை நிலைமைகள் அல்ல.")
    if 'weather' in e:
        w=e['weather'];p=e['period'];return choose(language,f"{p['start']} සිට {p['end']} දක්වා දින 7 න් {w['complete_days']} ක කාලගුණ දත්ත සම්පූර්ණය. දෛනික සාමාන්‍ය THI {n(w.get('mean_daily_thi'),2)} ය; උපරිම පැයක THI {n(w.get('max_hourly_thi'),2)} ය. මේවා අතීත නැවත විශ්ලේෂණ ඇස්තමේන්තුය; ගොවිපළේ මිනුම්, කාලගුණ පුරෝකථන හෝ හේතුවක් සඳහා සාක්ෂි නොවේ.",f"{p['start']} முதல் {p['end']} வரை 7 நாட்களில் {w['complete_days']} நாட்களின் வானிலைத் தரவு முழுமையாக உள்ளது. சராசரி தினசரி THI {n(w.get('mean_daily_thi'),2)}; அதிகபட்ச மணிநேர THI {n(w.get('max_hourly_thi'),2)}. இவை கடந்தகால மறுபகுப்பாய்வு மதிப்பீடுகள்; பண்ணை அளவீடுகளோ வானிலை முன்னறிவிப்போ காரணத்திற்கான சான்றோ அல்ல.")
    if e.get('milk_report'):
        from .milk_report import MilkReport, milk_explanation
        return milk_explanation(MilkReport.model_validate(e['milk_report']), language)
    p=e['latest_period'];sentences=[choose(language,f"අවසන් වාර්තාගත දින හත: {p['start']} සිට {p['end']} දක්වා.",f"கடைசிப் பதிவான ஏழு நாட்கள்: {p['start']} முதல் {p['end']} வரை.")]
    for source,m in e['milk'].items():
        label='DelPro' if source=='delpro' else choose(language,'නැව්ගත කිරීම්','விநியோகப் பதிவுகள்')
        sentences.append(choose(language,f"{label}: අවසන් කාලයේ දින 7 න් {m['current_observed_days']} ක වාර්තාගත කිරි {n(m['current_litres'],2)} ලීටර්; පෙර කාලයේ දින 7 න් {m['previous_observed_days']} ක {n(m['previous_litres'],2)} ලීටර්.",f"{label}: கடைசி காலத்தில் 7 நாட்களில் {m['current_observed_days']} நாட்களுக்கு {n(m['current_litres'],2)} லிட்டர் பதிவாகியுள்ளது; முந்தைய காலத்தில் 7 நாட்களில் {m['previous_observed_days']} நாட்களுக்கு {n(m['previous_litres'],2)} லிட்டர்."))
        sentences.append(choose(language,'මෙම දත්ත ආවරණයෙන් විශ්වාසදායක සතිපතා වෙනසක් ගණනය කළ නොහැක.','இந்தத் தரவு முழுமையுடன் நம்பகமான வாராந்திர மாற்றத்தைக் கணக்கிட முடியாது.') if m['change_pct'] is None else choose(language,f"සහාය ඇති සතිපතා වෙනස {n(m['change_pct'],2)}% ය.",f"தரவால் ஆதரிக்கப்படும் வாராந்திர மாற்றம் {n(m['change_pct'],2)}%."))
    return ' '.join(sentences)+choose(language,' මූලාශ්‍ර වෙන වෙනම තබා ඇත. අර්ධ එකතු සම්පූර්ණ සතියේ නිෂ්පාදනය නොවේ.',' மூலங்கள் தனித்தனியாக வைக்கப்பட்டுள்ளன. பகுதி மொத்தங்கள் முழு வார உற்பத்தி அல்ல.')

def localize_reply(reply,language):
    result=dict(reply,language=language)
    if language=='en':return result
    if reply.get('tool')=='c2_simulation' and reply.get('simulation_state'):
        from .c2_chat import explain
        result['answer']=explain(reply,language)
    else:
        result['answer']=successful_answer(reply,language) if reply['status']=='success' and reply.get('evidence') else status_answer(reply,language)
    if reply.get('title') in TITLES:result['title']=TITLES[reply['title']][0 if language=='si' else 1]
    result['warnings']=[translate_warning(text,language) for text in reply.get('warnings',[])]
    return result
