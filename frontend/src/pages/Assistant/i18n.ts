/** Static interface copy; native-language wording still requires speaker review. */
export type Language = 'en' | 'si' | 'ta';
export const LOCALES: Record<Language,string> = {en:'en-GB',si:'si-LK',ta:'ta-LK'};
const catalog: Record<string,Partial<Record<Language,string>>> = {
  "Digital Agronomist": {
    "si": "ඩිජිටල් කෘෂි සහායක",
    "ta": "டிஜிட்டல் விவசாய உதவியாளர்"
  },
  "Farm X · Your farm, explained": {
    "si": "Farm X · ඔබේ ගොවිපළ පිළිබඳ පැහැදිලි කිරීම",
    "ta": "Farm X · உங்கள் பண்ணையின் விளக்கம்"
  },
  "Local processing": {
    "si": "දේශීය සැකසුම",
    "ta": "உள்ளூர் செயலாக்கம்"
  },
  "History": {
    "si": "ඉතිහාසය",
    "ta": "வரலாறு"
  },
  "New conversation": {
    "si": "නව සංවාදය",
    "ta": "புதிய உரையாடல்"
  },
  "YOUR CONVERSATIONS": {
    "si": "ඔබේ සංවාද",
    "ta": "உங்கள் உரையாடல்கள்"
  },
  "Chat history": {
    "si": "සංවාද ඉතිහාසය",
    "ta": "உரையாடல் வரலாறு"
  },
  "Reopen a chat and continue where you left off.": {
    "si": "පෙර සංවාදයක් විවෘත කර නැවත ඉදිරියට යන්න.",
    "ta": "முந்தைய உரையாடலைத் திறந்து தொடருங்கள்."
  },
  "Your chats will appear here": {
    "si": "ඔබේ සංවාද මෙහි දිස්වේ",
    "ta": "உங்கள் உரையாடல்கள் இங்கே தோன்றும்"
  },
  "Start a conversation. It will be saved automatically in this browser.": {
    "si": "සංවාදයක් ආරම්භ කරන්න. එය මෙම බ්‍රවුසරයේ ස්වයංක්‍රීයව සුරැකේ.",
    "ta": "உரையாடலைத் தொடங்கவும். இந்த உலாவியில் தானாகச் சேமிக்கப்படும்."
  },
  "question": {
    "si": "ප්‍රශ්නය",
    "ta": "கேள்வி"
  },
  "questions": {
    "si": "ප්‍රශ්න",
    "ta": "கேள்விகள்"
  },
  "Delete conversation": {
    "si": "සංවාදය මකන්න",
    "ta": "உரையாடலை நீக்கு"
  },
  "Clear saved chats": {
    "si": "සුරැකි සංවාද මකන්න",
    "ta": "சேமித்த உரையாடல்களை அழி"
  },
  "Back up this role": {
    "si": "මෙම භූමිකාව උපස්ථ කරන්න",
    "ta": "இந்தப் பாத்திரத்தை காப்பெடு"
  },
  "Back up whole profile": {
    "si": "සම්පූර්ණ පැතිකඩ උපස්ථ කරන්න",
    "ta": "முழுச் சுயவிவரத்தையும் காப்பெடு"
  },
  "Restore backup": {
    "si": "උපස්ථය ප්‍රතිස්ථාපනය කරන්න",
    "ta": "காப்பை மீட்டெடு"
  },
  "Import earlier unassigned chats": {
    "si": "පෙර වෙන් නොකළ සංවාද ආයාත කරන්න",
    "ta": "முன்பு ஒதுக்கப்படாத உரையாடல்களை இறக்குமதி செய்"
  },
  "Saved for this profile and role in this browser only. Backup files contain conversations and evidence; keep them on a trusted device. These profiles do not restrict who can access chats.": {
    "si": "මෙම පැතිකඩ සහ භූමිකාව සඳහා මෙම බ්‍රවුසරයේ පමණක් සුරැකේ. උපස්ථවල සංවාද සහ සාක්ෂි ඇත; විශ්වාසදායක උපාංගයක තබන්න. පැතිකඩ ප්‍රවේශ පාලනයක් නොවේ.",
    "ta": "இந்தச் சுயவிவரத்திற்கும் பாத்திரத்திற்கும் இந்த உலாவியில் மட்டுமே சேமிக்கப்படும். காப்புகளில் உரையாடல்களும் சான்றுகளும் உள்ளன; நம்பகமான சாதனத்தில் வைக்கவும். சுயவிவரங்கள் அணுகலைக் கட்டுப்படுத்தாது."
  },
  "LET’S LOOK AT YOUR FARM": {
    "si": "ඔබේ ගොවිපළ පිළිබඳ බලමු",
    "ta": "உங்கள் பண்ணையைப் பார்ப்போம்"
  },
  "What would you like to understand?": {
    "si": "ඔබට දැනගැනීමට අවශ්‍ය කුමක්ද?",
    "ta": "நீங்கள் எதைப் புரிந்துகொள்ள விரும்புகிறீர்கள்?"
  },
  "Start with a question, or explore one of these topics.": {
    "si": "ප්‍රශ්නයක් අසන්න, නැතිනම් පහත මාතෘකාවක් තෝරන්න.",
    "ta": "ஒரு கேள்வியைக் கேளுங்கள் அல்லது கீழுள்ள தலைப்பைத் தேர்ந்தெடுக்கவும்."
  },
  "Milk production": {
    "si": "කිරි නිෂ්පාදනය",
    "ta": "பால் உற்பத்தி"
  },
  "Herd snapshot": {
    "si": "රංචු තොරතුරු",
    "ta": "மந்தை நிலவரம்"
  },
  "Weather context": {
    "si": "කාලගුණ තොරතුරු",
    "ta": "வானிலை விவரம்"
  },
  "Milk outlook": {
    "si": "කිරි පුරෝකථනය",
    "ta": "பால் முன்னறிவிப்பு"
  },
  "Historical risk": {
    "si": "අතීත අවදානම",
    "ta": "கடந்தகால அபாயம்"
  },
  "What-if scenario": {
    "si": "විකල්ප තත්ත්වය",
    "ta": "மாற்றுச் சூழல்"
  },
  "Totals, coverage and weekly change": {
    "si": "එකතු, ආවරණය සහ සතිපතා වෙනස",
    "ta": "மொத்தம், தரவு முழுமை, வாராந்திர மாற்றம்"
  },
  "Recorded herd and milking counts": {
    "si": "වාර්තාගත රංචු සහ කිරි දෙන සත්ව ගණන්",
    "ta": "பதிவான மந்தை மற்றும் கறவை எண்ணிக்கைகள்"
  },
  "Recorded heat conditions and coverage": {
    "si": "වාර්තාගත තාප තත්ත්ව සහ ආවරණය",
    "ta": "பதிவான வெப்பநிலைச் சூழல் மற்றும் தரவு முழுமை"
  },
  "Explore a stored model forecast": {
    "si": "ගබඩා කළ ආකෘති පුරෝකථනයක් බලන්න",
    "ta": "சேமித்த மாதிரி முன்னறிவிப்பைப் பாருங்கள்"
  },
  "Research scores with their limitations": {
    "si": "සීමා සහිත පර්යේෂණ ලකුණු",
    "ta": "வரம்புகளுடன் ஆய்வு மதிப்பெண்கள்"
  },
  "Check simulator availability": {
    "si": "අනුකාරකය තිබේද බලන්න",
    "ta": "உருவகப்படுத்தி உள்ளதா பார்க்கவும்"
  },
  "Compare the latest recorded milk week with the previous week.": {
    "si": "අවසන් වාර්තාගත සතියේ කිරි පෙර සතිය සමඟ සසඳන්න.",
    "ta": "கடைசியாகப் பதிவான வாரத்தின் பாலை முந்தைய வாரத்துடன் ஒப்பிடுங்கள்."
  },
  "Show the latest recorded herd summary.": {
    "si": "අවසන් වාර්තාගත රංචු සාරාංශය පෙන්වන්න.",
    "ta": "கடைசியாகப் பதிவான மந்தைச் சுருக்கத்தைக் காட்டுங்கள்."
  },
  "Summarize the historical weather and THI.": {
    "si": "අතීත කාලගුණය සහ THI සාරාංශ කරන්න.",
    "ta": "கடந்தகால வானிலை மற்றும் THI ஐச் சுருக்கமாகக் கூறுங்கள்."
  },
  "Show a daily milk forecast.": {
    "si": "දෛනික කිරි පුරෝකථනයක් පෙන්වන්න.",
    "ta": "தினசரி பால் முன்னறிவிப்பைக் காட்டுங்கள்."
  },
  "Show a historical risk assessment.": {
    "si": "අතීත අවදානම් ඇගයීමක් පෙන්වන්න.",
    "ta": "கடந்தகால அபாய மதிப்பீட்டைக் காட்டுங்கள்."
  },
  "Can I run a feed simulation?": {
    "si": "ආහාර අනුකරණයක් ක්‍රියාත්මක කළ හැකිද?",
    "ta": "தீவன உருவகப்படுத்தலை இயக்க முடியுமா?"
  },
  "You": {
    "si": "ඔබ",
    "ta": "நீங்கள்"
  },
  "One more detail": {
    "si": "තවත් විස්තරයක්",
    "ta": "மேலும் ஒரு விவரம்"
  },
  "Let’s check that": {
    "si": "එය පරීක්ෂා කරමු",
    "ta": "அதைச் சரிபார்ப்போம்"
  },
  "From your records": {
    "si": "ඔබේ වාර්තාවලින්",
    "ta": "உங்கள் பதிவுகளிலிருந்து"
  },
  "Clarification": {
    "si": "පැහැදිලි කිරීමක්",
    "ta": "விளக்கம் தேவை"
  },
  "Information": {
    "si": "තොරතුරු",
    "ta": "தகவல்"
  },
  "Keep in mind": {
    "si": "සලකා බලන්න",
    "ta": "கவனத்தில் கொள்ளுங்கள்"
  },
  "Checking your local records…": {
    "si": "දේශීය වාර්තා පරීක්ෂා කරමින්…",
    "ta": "உள்ளூர் பதிவுகளைச் சரிபார்க்கிறது…"
  },
  "Ask about your farm": {
    "si": "ඔබේ ගොවිපළ ගැන අසන්න",
    "ta": "உங்கள் பண்ணையைப் பற்றிக் கேளுங்கள்"
  },
  "Reply with a date in YYYY-MM-DD…": {
    "si": "YYYY-MM-DD ආකාරයෙන් දිනයක් දෙන්න…",
    "ta": "YYYY-MM-DD வடிவில் ஒரு தேதியைத் தரவும்…"
  },
  "Ask about milk, your herd, forecasts or historical risk…": {
    "si": "කිරි, රංචුව, පුරෝකථන හෝ අතීත අවදානම ගැන අසන්න…",
    "ta": "பால், மந்தை, முன்னறிவிப்பு அல்லது கடந்தகால அபாயம் பற்றிக் கேளுங்கள்…"
  },
  "Add dates": {
    "si": "දින එක් කරන්න",
    "ta": "தேதிகளைச் சேர்"
  },
  "Hide dates": {
    "si": "දින සඟවන්න",
    "ta": "தேதிகளை மறை"
  },
  "Local factual answers": {
    "si": "දේශීය දත්ත මත පිළිතුරු",
    "ta": "உள்ளூர் தரவு சார்ந்த பதில்கள்"
  },
  "Send question": {
    "si": "ප්‍රශ්නය යවන්න",
    "ta": "கேள்வியை அனுப்பு"
  },
  "Checking…": {
    "si": "පරීක්ෂා කරමින්…",
    "ta": "சரிபார்க்கிறது…"
  },
  "Reference date": {
    "si": "යොමු දිනය",
    "ta": "குறிப்புத் தேதி"
  },
  "Forecast target": {
    "si": "පුරෝකථන ඉලක්කය",
    "ta": "முன்னறிவிப்பு இலக்கு"
  },
  "Forecast period": {
    "si": "පුරෝකථන කාල පරාසය",
    "ta": "முன்னறிவிப்புக் காலம்"
  },
  "Daily": {
    "si": "දෛනික",
    "ta": "தினசரி"
  },
  "Weekly": {
    "si": "සතිපතා",
    "ta": "வாராந்திர"
  },
  "Monthly": {
    "si": "මාසික",
    "ta": "மாதாந்திர"
  },
  "Clear dates": {
    "si": "දින හිස් කරන්න",
    "ta": "தேதிகளை அழி"
  },
  "Answers use recorded evidence. Forecasts are estimates; research assessments are not live alerts.": {
    "si": "පිළිතුරු වාර්තාගත සාක්ෂි මත පදනම් වේ. පුරෝකථන ඇස්තමේන්තුය; පර්යේෂණ ඇගයීම් සජීවී අනතුරු ඇඟවීම් නොවේ.",
    "ta": "பதில்கள் பதிவான சான்றுகளைப் பயன்படுத்துகின்றன. முன்னறிவிப்புகள் மதிப்பீடுகள்; ஆய்வு மதிப்பீடுகள் நேரடி எச்சரிக்கைகள் அல்ல."
  },
  "New replies use the selected language. Saved replies keep their original language.": {
    "si": "නව පිළිතුරු තෝරාගත් භාෂාවෙන් ලැබේ. සුරැකි පිළිතුරු මුල් භාෂාවෙන් පවතී.",
    "ta": "புதிய பதில்கள் தேர்ந்தெடுத்த மொழியில் வரும். சேமித்த பதில்கள் அவற்றின் அசல் மொழியிலேயே இருக்கும்."
  },
  "Retry saving": {
    "si": "නැවත සුරකින්න",
    "ta": "மீண்டும் சேமி"
  },
  "Your draft is too long. Shorten it to 1,500 characters before sending.": {
    "si": "කෙටුම්පත දිග වැඩිය. යැවීමට පෙර අක්ෂර 1,500 දක්වා කෙටි කරන්න.",
    "ta": "வரைவு மிகவும் நீளமாக உள்ளது. அனுப்புமுன் 1,500 எழுத்துகளுக்குள் குறைக்கவும்."
  },
  "I could not reach the local assistant. Check the backend and try sending your question again.": {
    "si": "දේශීය සහායකයට සම්බන්ධ විය නොහැක. පසුපස සේවාව පරීක්ෂා කර ප්‍රශ්නය නැවත යවන්න.",
    "ta": "உள்ளூர் உதவியாளரை அணுக முடியவில்லை. பின்தளச் சேவையைச் சரிபார்த்து மீண்டும் அனுப்பவும்."
  },
  "This request was interrupted when you left the conversation. Please send the question again.": {
    "si": "සංවාදයෙන් ඉවත් වූ විට මෙම ඉල්ලීම නතර විය. ප්‍රශ්නය නැවත යවන්න.",
    "ta": "உரையாடலை விட்டு வெளியேறியதால் கோரிக்கை நிறுத்தப்பட்டது. மீண்டும் கேள்வியை அனுப்பவும்."
  },
  "This request was interrupted before an answer was saved. Please send the question again.": {
    "si": "පිළිතුර සුරැකීමට පෙර ඉල්ලීම නතර විය. ප්‍රශ්නය නැවත යවන්න.",
    "ta": "பதிலைச் சேமிக்கும் முன் கோரிக்கை நிறுத்தப்பட்டது. மீண்டும் கேள்வியை அனுப்பவும்."
  },
  "View evidence & dates": {
    "si": "සාක්ෂි සහ දින බලන්න",
    "ta": "சான்றுகள் மற்றும் தேதிகளைப் பார்"
  },
  "Supporting records, dates and source details": {
    "si": "ආධාරක වාර්තා, දින සහ මූලාශ්‍ර විස්තර",
    "ta": "ஆதாரப் பதிவுகள், தேதிகள் மற்றும் மூல விவரங்கள்"
  },
  "Evidence dates": {
    "si": "සාක්ෂි දින",
    "ta": "சான்றுத் தேதிகள்"
  },
  "Source & model details": {
    "si": "මූලාශ්‍ර සහ ආකෘති විස්තර",
    "ta": "மூலம் மற்றும் மாதிரி விவரங்கள்"
  },
  "Not supplied": {
    "si": "ලබා දී නැත",
    "ta": "வழங்கப்படவில்லை"
  },
  "None supplied": {
    "si": "කිසිවක් ලබා දී නැත",
    "ta": "எதுவும் வழங்கப்படவில்லை"
  },
  "Yes": {
    "si": "ඔව්",
    "ta": "ஆம்"
  },
  "No": {
    "si": "නැත",
    "ta": "இல்லை"
  },
  " of 7 days": {
    "si": " / දින 7",
    "ta": " / 7 நாட்கள்"
  },
  "Sri Lanka time": {
    "si": "ශ්‍රී ලංකා වේලාව",
    "ta": "இலங்கை நேரம்"
  },
  "Values come from the supplied evidence. Decimals are rounded to two places; missing values remain unfilled.": {
    "si": "අගයන් ලබා දුන් සාක්ෂිවලින් වේ. දශම ස්ථාන දෙකකට වට කර ඇත; නැති අගයන් පුරවා නැත.",
    "ta": "மதிப்புகள் வழங்கப்பட்ட சான்றுகளிலிருந்து வருகின்றன. தசமங்கள் இரண்டு இடங்களுக்கு வட்டமிடப்படுகின்றன; விடுபட்ட மதிப்புகள் நிரப்பப்படவில்லை."
  },
  "Records through": {
    "si": "වාර්තා අවසන් දිනය",
    "ta": "பதிவுகள் உள்ள கடைசித் தேதி"
  },
  "Requested reference date": {
    "si": "ඉල්ලූ යොමු දිනය",
    "ta": "கோரிய குறிப்புத் தேதி"
  },
  "Forecast origin": {
    "si": "පුරෝකථන ආරම්භය",
    "ta": "முன்னறிவிப்புத் தொடக்கம்"
  },
  "Assessment date": {
    "si": "ඇගයීම් දිනය",
    "ta": "மதிப்பீட்டுத் தேதி"
  },
  "Assessment cutoff": {
    "si": "ඇගයීම් දත්ත සීමාව",
    "ta": "மதிப்பீட்டுத் தரவு முடிவு"
  },
  "Generated at": {
    "si": "නිර්මාණය කළ වේලාව",
    "ta": "உருவாக்கிய நேரம்"
  },
  "Core publication": {
    "si": "Core ප්‍රකාශනය",
    "ta": "Core வெளியீடு"
  },
  "Source core publication": {
    "si": "මූලාශ්‍ර core ප්‍රකාශනය",
    "ta": "மூல core வெளியீடு"
  },
  "Model version": {
    "si": "ආකෘති අනුවාදය",
    "ta": "மாதிரிப் பதிப்பு"
  },
  "Output contract": {
    "si": "ප්‍රතිඵල ගිවිසුම",
    "ta": "வெளியீட்டு ஒப்பந்தம்"
  },
  "Scoring method": {
    "si": "ලකුණු ක්‍රමය",
    "ta": "மதிப்பீட்டு முறை"
  },
  "Assessment basis": {
    "si": "ඇගයීම් පදනම",
    "ta": "மதிப்பீட்டின் அடிப்படை"
  },
  "Model status": {
    "si": "ආකෘති තත්ත්වය",
    "ta": "மாதிரி நிலை"
  },
  "Data source": {
    "si": "දත්ත මූලාශ්‍රය",
    "ta": "தரவு மூலம்"
  },
  "Total animals": {
    "si": "මුළු සතුන්",
    "ta": "மொத்த விலங்குகள்"
  },
  "Milking animals": {
    "si": "කිරි දෙන සතුන්",
    "ta": "கறவை விலங்குகள்"
  },
  "Dry animals": {
    "si": "වියළි සතුන්",
    "ta": "உலர் விலங்குகள்"
  },
  "Pregnant, not milking": {
    "si": "ගැබ්ගත්, කිරි නොදෙන",
    "ta": "சினையுள்ள, கறவையில்லாத"
  },
  "Unknown herd state": {
    "si": "නොදන්නා රංචු තත්ත්වය",
    "ta": "தெரியாத மந்தை நிலை"
  },
  "Weather observations": {
    "si": "කාලගුණ වාර්තා",
    "ta": "வானிலைப் பதிவுகள்"
  },
  "Mean daily THI": {
    "si": "දෛනික සාමාන්‍ය THI",
    "ta": "சராசரி தினசரி THI"
  },
  "Maximum hourly THI": {
    "si": "උපරිම පැයක THI",
    "ta": "அதிகபட்ச மணிநேர THI"
  },
  "Complete weather days": {
    "si": "සම්පූර්ණ කාලගුණ දින",
    "ta": "முழுமையான வானிலை நாட்கள்"
  },
  "Recorded days": {
    "si": "වාර්තාගත දින",
    "ta": "பதிவுசெய்யப்பட்ட நாட்கள்"
  },
  "Latest recorded period": {
    "si": "අවසන් වාර්තාගත කාලය",
    "ta": "கடைசிப் பதிவுக் காலம்"
  },
  "Previous recorded period": {
    "si": "පෙර වාර්තාගත කාලය",
    "ta": "முந்தைய பதிவுக் காலம்"
  },
  "Observation period": {
    "si": "නිරීක්ෂණ කාලය",
    "ta": "கண்காணிப்புக் காலம்"
  },
  "From": {
    "si": "සිට",
    "ta": "முதல்"
  },
  "To": {
    "si": "දක්වා",
    "ta": "வரை"
  },
  "Milk records": {
    "si": "කිරි වාර්තා",
    "ta": "பால் பதிவுகள்"
  },
  "DelPro records": {
    "si": "DelPro වාර්තා",
    "ta": "DelPro பதிவுகள்"
  },
  "Shipment records": {
    "si": "නැව්ගත කිරීමේ වාර්තා",
    "ta": "விநியோகப் பதிவுகள்"
  },
  "Latest period milk": {
    "si": "අවසන් කාලයේ කිරි",
    "ta": "கடைசி காலத்தின் பால்"
  },
  "Previous period milk": {
    "si": "පෙර කාලයේ කිරි",
    "ta": "முந்தைய காலத்தின் பால்"
  },
  "Latest period coverage": {
    "si": "අවසන් කාලයේ ආවරණය",
    "ta": "கடைசி காலத் தரவு முழுமை"
  },
  "Previous period coverage": {
    "si": "පෙර කාලයේ ආවරණය",
    "ta": "முந்தைய காலத் தரவு முழுமை"
  },
  "Weekly change": {
    "si": "සතිපතා වෙනස",
    "ta": "வாராந்திர மாற்றம்"
  },
  "Point forecast": {
    "si": "පුරෝකථන අගය",
    "ta": "முன்னறிவிப்பு மதிப்பு"
  },
  "Lower bound": {
    "si": "පහළ සීමාව",
    "ta": "கீழ் வரம்பு"
  },
  "Upper bound": {
    "si": "ඉහළ සීමාව",
    "ta": "மேல் வரம்பு"
  },
  "Producer quality flags": {
    "si": "නිෂ්පාදක තත්ත්ව සලකුණු",
    "ta": "தயாரிப்பாளரின் தரக் குறிகள்"
  },
  "Forecast measure": {
    "si": "පුරෝකථන මිනුම",
    "ta": "முன்னறிவிப்பு அளவு"
  },
  "Combined research score": {
    "si": "ඒකාබද්ධ පර්යේෂණ ලකුණ",
    "ta": "ஒருங்கிணைந்த ஆய்வு மதிப்பெண்"
  },
  "Climate score": {
    "si": "දේශගුණ ලකුණ",
    "ta": "காலநிலை மதிப்பெண்"
  },
  "Biological score": {
    "si": "ජීව විද්‍යාත්මක ලකුණ",
    "ta": "உயிரியல் மதிப்பெண்"
  },
  "Operational score": {
    "si": "මෙහෙයුම් ලකුණ",
    "ta": "செயல்பாட்டு மதிப்பெண்"
  },
  "Assessments used": {
    "si": "භාවිත කළ ඇගයීම්",
    "ta": "பயன்படுத்திய மதிப்பீடுகள்"
  },
  "Research only": {
    "si": "පර්යේෂණ සඳහා පමණි",
    "ta": "ஆய்வுக்காக மட்டுமே"
  },
  "Live warnings permitted": {
    "si": "සජීවී අනතුරු ඇඟවීම් සඳහා අවසර",
    "ta": "நேரடி எச்சரிக்கைகள் அனுமதி"
  },
  "Published farm records": {
    "si": "ප්‍රකාශිත ගොවිපළ වාර්තා",
    "ta": "வெளியிடப்பட்ட பண்ணைப் பதிவுகள்"
  },
  "Stored C4 research assessments": {
    "si": "ගබඩා කළ C4 පර්යේෂණ ඇගයීම්",
    "ta": "சேமித்த C4 ஆய்வு மதிப்பீடுகள்"
  },
  "Herd milk": {
    "si": "රංචු කිරි",
    "ta": "மந்தைப் பால்"
  },
  "Total herd": {
    "si": "මුළු රංචුව",
    "ta": "மொத்த மந்தை"
  },
  "Calvings": {
    "si": "පැටවුන් බිහිවීම්",
    "ta": "கன்று ஈனுதல்கள்"
  },
  "Dry-offs": {
    "si": "කිරි වේලීම්",
    "ta": "கறவை நிறுத்தங்கள்"
  },
  "Recorded abortions": {
    "si": "වාර්තාගත ගබ්සා",
    "ta": "பதிவுசெய்த கருச்சிதைவுகள்"
  },
  "Speech language": {
    "si": "කථන භාෂාව",
    "ta": "பேச்சு மொழி"
  },
  "Speak question": {
    "si": "ප්‍රශ්නය කතා කරන්න",
    "ta": "கேள்வியைப் பேசுங்கள்"
  },
  "Stop": {
    "si": "නවත්වන්න",
    "ta": "நிறுத்து"
  },
  "Preparing…": {
    "si": "සූදානම් කරමින්…",
    "ta": "தயாராகிறது…"
  },
  "Transcribing…": {
    "si": "හඬ පෙළට හරවමින්…",
    "ta": "பேச்சை எழுத்தாக்குகிறது…"
  },
  "Up to 30 seconds · processed locally": {
    "si": "තත්පර 30 දක්වා · දේශීයව සකසයි",
    "ta": "30 வினாடிகள் வரை · உள்ளூரில் செயலாக்கம்"
  },
  "Read aloud": {
    "si": "හඬින් කියවන්න",
    "ta": "உரக்க வாசி"
  },
  "Stop reading": {
    "si": "කියවීම නවත්වන්න",
    "ta": "வாசிப்பை நிறுத்து"
  },
  "Local voice unavailable": {
    "si": "දේශීය හඬක් නැත",
    "ta": "உள்ளூர் குரல் கிடைக்கவில்லை"
  },
  "Uses an installed local voice": {
    "si": "ස්ථාපිත දේශීය හඬක් භාවිතා කරයි",
    "ta": "நிறுவப்பட்ட உள்ளூர் குரலைப் பயன்படுத்துகிறது"
  },
  "A local voice for this language is required; remote voices are not used": {
    "si": "මෙම භාෂාවට දේශීය හඬක් අවශ්‍යය; බාහිර හඬ සේවා භාවිතා නොවේ",
    "ta": "இந்த மொழிக்கான உள்ளூர் குரல் தேவை; தொலைக் குரல்கள் பயன்படுத்தப்படாது"
  },
  "Transcript added to your draft. Review it before sending.": {
    "si": "හඳුනාගත් පෙළ කෙටුම්පතට එක් කළා. යැවීමට පෙර පරීක්ෂා කරන්න.",
    "ta": "அடையாளம் கண்ட உரை வரைவில் சேர்க்கப்பட்டது. அனுப்புமுன் சரிபார்க்கவும்."
  },
  "Speech is transcribed in the selected input language. Answers use the chat language.": {
    "si": "කථාව තෝරාගත් ආදාන භාෂාවෙන් පෙළට හැරේ. පිළිතුරු සංවාද භාෂාවෙන් ලැබේ.",
    "ta": "பேச்சு தேர்ந்தெடுத்த உள்ளீட்டு மொழியில் எழுத்தாக்கப்படும். பதில்கள் உரையாடல் மொழியில் வரும்."
  },
  "Chat profile": {
    "si": "සංවාද පැතිකඩ",
    "ta": "உரையாடல் சுயவிவரம்"
  },
  "Add profile": {
    "si": "පැතිකඩ එක් කරන්න",
    "ta": "சுயவிவரத்தைச் சேர்"
  },
  "Farm worker": {
    "si": "ගොවිපළ සේවක",
    "ta": "பண்ணைப் பணியாளர்"
  },
  "Veterinarian": {
    "si": "පශු වෛද්‍ය",
    "ta": "கால்நடை மருத்துவர்"
  },
  "Farm manager": {
    "si": "ගොවිපළ කළමනාකරු",
    "ta": "பண்ணை மேலாளர்"
  },
  "Board management": {
    "si": "පාලක මණ්ඩලය",
    "ta": "நிர்வாகக் குழு"
  },
  "Local profiles organise chats. They do not provide sign-in or access control.": {
    "si": "දේශීය පැතිකඩ සංවාද සංවිධානය කරයි. ඒවා පිවිසුම් හෝ ප්‍රවේශ පාලන ලබා නොදෙයි.",
    "ta": "உள்ளூர் சுயவிவரங்கள் உரையாடல்களை ஒழுங்குபடுத்துகின்றன. உள்நுழைவு அல்லது அணுகல் கட்டுப்பாட்டை வழங்காது."
  },
  "Answer language": {
    "si": "පිළිතුරු භාෂාව",
    "ta": "பதில் மொழி"
  },
  "Delete this saved conversation from this browser?": {
    "si": "මෙම සුරැකි සංවාදය මෙම බ්‍රවුසරයෙන් මකන්නද?",
    "ta": "இந்தச் சேமித்த உரையாடலை இந்த உலாவியிலிருந்து நீக்கவா?"
  },
  "Clear chats for {scope} only? This also clears its open conversation.": {
    "si": "{scope} සඳහා පමණක් සංවාද මකන්නද? එහි විවෘත සංවාදයද මැකේ.",
    "ta": "{scope} உரையாடல்களை மட்டும் அழிக்கவா? அதன் திறந்த உரையாடலும் அழியும்."
  },
  "Copy the earlier, unassigned chat history into {scope}? Existing chats will be kept and the original history will remain available.": {
    "si": "පෙර වෙන් නොකළ සංවාද {scope} වෙත පිටපත් කරන්නද? පවතින සංවාද සහ මුල් ඉතිහාසය රැකේ.",
    "ta": "முன்பு ஒதுக்கப்படாத வரலாற்றை {scope} க்கு நகலெடுக்கவா? ஏற்கனவே உள்ள உரையாடல்களும் மூல வரலாறும் பாதுகாக்கப்படும்."
  },
  "Imported {added} earlier chats. Kept {skipped} chats already present. The original history was preserved.": {
    "si": "පෙර සංවාද {added} ක් ආයාත විය. පවතින සංවාද {skipped} ක් සහ මුල් ඉතිහාසය රැක ඇත.",
    "ta": "முந்தைய {added} உரையாடல்கள் இறக்குமதி செய்யப்பட்டன. ஏற்கனவே உள்ள {skipped} உரையாடல்களும் மூல வரலாறும் பாதுகாக்கப்பட்டன."
  },
  "Restore {profile} for {roles}? Existing conversations with matching IDs will be kept unchanged. Other profiles and roles will not be changed.": {
    "si": "{roles} සඳහා {profile} ප්‍රතිස්ථාපනය කරන්නද? එකම හැඳුනුම් සහිත සංවාද නොවෙනස්ව රැකේ. වෙනත් පැතිකඩ සහ භූමිකා වෙනස් නොවේ.",
    "ta": "{roles} க்கான {profile} ஐ மீட்டெடுக்கவா? பொருந்தும் அடையாளமுள்ள உரையாடல்கள் மாறாமல் இருக்கும். மற்ற சுயவிவரங்களும் பாத்திரங்களும் மாற்றப்படாது."
  },
  "Restored {added} conversations. Kept {skipped} existing conversations with matching IDs. Other profile and role histories were preserved.": {
    "si": "සංවාද {added} ක් ප්‍රතිස්ථාපනය විය. ගැළපෙන පවතින සංවාද {skipped} ක් රැක ඇත. වෙනත් පැතිකඩ සහ භූමිකා ඉතිහාස රැක ඇත.",
    "ta": "{added} உரையாடல்கள் மீட்டெடுக்கப்பட்டன. பொருந்தும் {skipped} உரையாடல்கள் பாதுகாக்கப்பட்டன. மற்ற சுயவிவர, பாத்திர வரலாறுகள் பாதுகாக்கப்பட்டன."
  },
  "Please shorten the question to 1,500 characters before sending.": {
    "si": "යැවීමට පෙර ප්‍රශ්නය අක්ෂර 1,500 කට කෙටි කරන්න.",
    "ta": "அனுப்புவதற்கு முன் கேள்வியை 1,500 எழுத்துகளுக்குள் சுருக்கவும்."
  },
  "Browser storage is unavailable. Chats will remain in memory until you leave this page.": {
    "si": "බ්‍රවුසර ගබඩාව නොමැත. මෙම පිටුවෙන් ඉවත් වන තෙක් සංවාද මතකයේ පවතී.",
    "ta": "உலாவிச் சேமிப்பகம் கிடைக்கவில்லை. இப்பக்கத்தை விட்டு வெளியேறும் வரை உரையாடல்கள் நினைவகத்தில் இருக்கும்."
  },
  "Browser storage is unavailable. Chats are currently held in memory only.": {
    "si": "බ්‍රවුසර ගබඩාව නොමැත. සංවාද දැනට මතකයේ පමණි.",
    "ta": "உலாவிச் சேமிப்பகம் கிடைக்கவில்லை. உரையாடல்கள் தற்போது நினைவகத்தில் மட்டுமே உள்ளன."
  },
  "Browser storage remains unavailable. Chats are held in memory only.": {
    "si": "බ්‍රවුසර ගබඩාව තවම නොමැත. සංවාද මතකයේ පමණි.",
    "ta": "உலாவிச் சேமிப்பகம் இன்னும் கிடைக்கவில்லை. உரையாடல்கள் நினைவகத்தில் மட்டுமே உள்ளன."
  },
  "Saved history changed in another tab. Reload this page before saving more changes; your current conversation remains in memory.": {
    "si": "වෙනත් ටැබයක සුරැකි ඉතිහාසය වෙනස් විය. තවත් වෙනස්කම් සුරැකීමට පෙර පිටුව නැවත පූරණය කරන්න. වත්මන් සංවාදය මතකයේ පවතී.",
    "ta": "வேறு தாவலில் வரலாறு மாற்றப்பட்டது. மேலும் சேமிக்கும் முன் இப்பக்கத்தை மீண்டும் ஏற்றவும். தற்போதைய உரையாடல் நினைவகத்தில் உள்ளது."
  },
  "Saved chats could not be opened. You can continue in memory. Use Clear saved chats to reset local history.": {
    "si": "සුරැකි සංවාද විවෘත කළ නොහැක. මතකයේ ඉදිරියට යා හැක. ඉතිහාසය නැවත සැකසීමට සුරැකි සංවාද මකන්න.",
    "ta": "சேமித்த உரையாடல்களைத் திறக்க முடியவில்லை. நினைவகத்தில் தொடரலாம். உள்ளூர் வரலாற்றை மீட்டமைக்க சேமித்த உரையாடல்களை அழிக்கவும்."
  },
  "Chat history could not be saved in this browser. Keep this page open to retain the current conversation, or free browser storage and retry.": {
    "si": "සංවාද ඉතිහාසය සුරැකිය නොහැක. වත්මන් සංවාදය රැකීමට පිටුව විවෘතව තබන්න, නැතිනම් ගබඩා ඉඩ නිදහස් කර නැවත උත්සාහ කරන්න.",
    "ta": "வரலாற்றைச் சேமிக்க முடியவில்லை. தற்போதைய உரையாடலை வைத்திருக்க பக்கத்தைத் திறந்தே வைக்கவும் அல்லது சேமிப்பிடத்தை விடுவித்து மீண்டும் முயலவும்."
  },
  "Earlier history could not be imported. Its original saved copy has not been changed.": {
    "si": "පෙර ඉතිහාසය ආයාත කළ නොහැක. මුල් සුරැකි පිටපත වෙනස් කර නැත.",
    "ta": "முந்தைய வரலாற்றை இறக்குமதி செய்ய முடியவில்லை. அதன் மூலச் சேமிப்பு மாற்றப்படவில்லை."
  },
  "Save the current conversation before restoring a backup.": {
    "si": "උපස්ථයක් ප්‍රතිස්ථාපනය කිරීමට පෙර වත්මන් සංවාදය සුරකින්න.",
    "ta": "காப்பை மீட்டெடுக்கும் முன் தற்போதைய உரையாடலைச் சேமிக்கவும்."
  },
  "Local profiles could not be opened. Existing profile records will not be overwritten automatically.": {
    "si": "දේශීය පැතිකඩ විවෘත කළ නොහැක. පවතින පැතිකඩ ස්වයංක්‍රීයව ප්‍රතිස්ථාපනය නොවේ.",
    "ta": "உள்ளூர் சுயவிவரங்களைத் திறக்க முடியவில்லை. ஏற்கனவே உள்ள பதிவுகள் தானாக மேலெழுதப்படாது."
  },
  "Profiles changed in another tab. Reload this page before modifying profiles or restoring backups.": {
    "si": "වෙනත් ටැබයක පැතිකඩ වෙනස් විය. පැතිකඩ වෙනස් කිරීමට හෝ උපස්ථ ප්‍රතිස්ථාපනයට පෙර පිටුව නැවත පූරණය කරන්න.",
    "ta": "வேறு தாவலில் சுயவிவரங்கள் மாற்றப்பட்டன. மாற்றுவதற்கோ காப்பை மீட்டெடுப்பதற்கோ முன் பக்கத்தை மீண்டும் ஏற்றவும்."
  },
  "Profile changes could not be saved. Check browser storage; your existing profiles remain selected.": {
    "si": "පැතිකඩ වෙනස්කම් සුරැකිය නොහැක. බ්‍රවුසර ගබඩාව පරීක්ෂා කරන්න. පවතින පැතිකඩ තේරීම රැකේ.",
    "ta": "சுயவிவர மாற்றங்களைச் சேமிக்க முடியவில்லை. உலாவிச் சேமிப்பகத்தைச் சரிபார்க்கவும். தற்போதைய தேர்வு தொடரும்."
  },
  "Backup download requested. Keep this file on a trusted device; it contains saved conversations and evidence.": {
    "si": "උපස්ථ බාගැනීම ඉල්ලන ලදී. සංවාද සහ සාක්ෂි අඩංගු බැවින් ගොනුව විශ්වාසදායක උපාංගයක තබන්න.",
    "ta": "காப்புப் பதிவிறக்கம் கோரப்பட்டது. இதில் உரையாடல்களும் சான்றுகளும் இருப்பதால் நம்பகமான சாதனத்தில் வைக்கவும்."
  },
  "Backup could not be created. Check local browser storage; no incomplete profile backup was downloaded.": {
    "si": "උපස්ථය සෑදිය නොහැක. බ්‍රවුසර ගබඩාව පරීක්ෂා කරන්න. අසම්පූර්ණ උපස්ථයක් බාගත කර නැත.",
    "ta": "காப்பை உருவாக்க முடியவில்லை. உலாவிச் சேமிப்பகத்தைச் சரிபார்க்கவும். முழுமையற்ற காப்பு பதிவிறக்கப்படவில்லை."
  },
  "Select a backup smaller than 10 MB.": {
    "si": "10 MB ට අඩු උපස්ථයක් තෝරන්න.",
    "ta": "10 MB க்கும் சிறிய காப்பைத் தேர்ந்தெடுக்கவும்."
  },
  "This is not a valid C3 profile backup. No saved chats were changed.": {
    "si": "මෙය වලංගු C3 පැතිකඩ උපස්ථයක් නොවේ. සුරැකි සංවාද වෙනස් කර නැත.",
    "ta": "இது செல்லுபடியாகும் C3 சுயவிவரக் காப்பல்ல. சேமித்த உரையாடல்கள் மாற்றப்படவில்லை."
  },
  "Restore failed. Keep your original backup.": {
    "si": "ප්‍රතිස්ථාපනය අසමත්ය. මුල් උපස්ථය රැකගන්න.",
    "ta": "மீட்டெடுத்தல் தோல்வியடைந்தது. மூலக் காப்பைப் பாதுகாக்கவும்."
  },
  "Voice input requires a backend on this computer. Audio was not recorded or sent.": {
    "si": "හඬ ආදානයට මෙම පරිගණකයේ පසුපස සේවාවක් අවශ්‍යය. හඬ පටිගත හෝ යවා නැත.",
    "ta": "குரல் உள்ளீட்டிற்கு இந்தக் கணினியில் பின்தளச் சேவை தேவை. ஒலி பதிவு செய்யப்படவோ அனுப்பப்படவோ இல்லை."
  },
  "Microphone recording is unavailable here. Use Chrome or Edge on localhost.": {
    "si": "මෙහි මයික්‍රෆෝන පටිගත කිරීම නොමැත. localhost හි Chrome හෝ Edge භාවිතා කරන්න.",
    "ta": "இங்கு ஒலிப்பதிவு கிடைக்கவில்லை. localhost இல் Chrome அல்லது Edge பயன்படுத்தவும்."
  },
  "Local speech setup is incomplete. Install the C3 voice runtime and speech model first.": {
    "si": "දේශීය හඬ සැකසුම අසම්පූර්ණය. පළමුව C3 හඬ පද්ධතිය සහ ආකෘතිය ස්ථාපනය කරන්න.",
    "ta": "உள்ளூர் குரல் அமைப்பு முழுமையடையவில்லை. முதலில் C3 குரல் இயக்கச் சூழலையும் மாதிரியையும் நிறுவவும்."
  },
  "Allow microphone access to record a short question.": {
    "si": "කෙටි ප්‍රශ්නයක් පටිගත කිරීමට මයික්‍රෆෝන අවසරය දෙන්න.",
    "ta": "சிறிய கேள்வியைப் பதிவு செய்ய ஒலிவாங்கி அனுமதியை வழங்கவும்."
  },
  "This browser has no supported audio recording format. Try Chrome or Edge.": {
    "si": "මෙම බ්‍රවුසරයේ සුදුසු හඬ පටිගත ආකෘතියක් නොමැත. Chrome හෝ Edge භාවිතා කරන්න.",
    "ta": "இந்த உலாவியில் ஆதரிக்கப்படும் ஒலிப்பதிவு வடிவம் இல்லை. Chrome அல்லது Edge முயலவும்."
  },
  "Microphone recording failed. Please try again.": {
    "si": "මයික්‍රෆෝන පටිගත කිරීම අසමත්ය. නැවත උත්සාහ කරන්න.",
    "ta": "ஒலிப்பதிவு தோல்வியடைந்தது. மீண்டும் முயலவும்."
  },
  "No usable audio was captured. Record a short question, up to 30 seconds.": {
    "si": "භාවිතයට සුදුසු හඬක් නොලැබුණි. තත්පර 30 කට අඩු කෙටි ප්‍රශ්නයක් පටිගත කරන්න.",
    "ta": "பயன்படுத்தக்கூடிய ஒலி கிடைக்கவில்லை. 30 நொடிகளுக்குள் சிறிய கேள்வியைப் பதிவு செய்யவும்."
  },
  "No local speech transcript was returned.": {
    "si": "දේශීය හඬ පිටපතක් නොලැබුණි.",
    "ta": "உள்ளூர் ஒலி எழுத்துப்பதிவு கிடைக்கவில்லை."
  },
  "Local transcription failed. Please try again.": {
    "si": "දේශීය හඬ ලිවීම අසමත්ය. නැවත උත්සාහ කරන්න.",
    "ta": "உள்ளூர் எழுத்துப்பதிவு தோல்வியடைந்தது. மீண்டும் முயலவும்."
  },
  "Microphone permission was denied. Allow access in your browser, then try again.": {
    "si": "මයික්‍රෆෝන අවසරය ප්‍රතික්ෂේප විය. බ්‍රවුසරයෙන් අවසර දී නැවත උත්සාහ කරන්න.",
    "ta": "ஒலிவாங்கி அனுமதி மறுக்கப்பட்டது. உலாவியில் அனுமதித்து மீண்டும் முயலவும்."
  },
  "Voice input could not start.": {
    "si": "හඬ ආදානය ආරම්භ කළ නොහැක.",
    "ta": "குரல் உள்ளீட்டைத் தொடங்க முடியவில்லை."
  },
  "Run a THI or milking-frequency what-if.": {
    "si": "THI හෝ කිරි දෙවීම් වාර ගණන වෙනස් කර අනුකරණයක් කරන්න.",
    "ta": "THI அல்லது கறவை எண்ணிக்கை மாற்றத்தை உருவகப்படுத்துங்கள்."
  },
  "Run the selected what-if simulation.": {
    "si": "තෝරාගත් තත්ත්ව අනුකරණය ක්‍රියාත්මක කරන්න.",
    "ta": "தேர்ந்தெடுத்த மாற்று உருவகப்படுத்தலை இயக்குங்கள்."
  },
  "Compare explicit scenario inputs": {
    "si": "ඔබ තෝරාගත් තත්ත්ව සසඳන්න",
    "ta": "நீங்கள் தேர்ந்தெடுத்த உள்ளீடுகளை ஒப்பிடுங்கள்"
  },
  "Set up your what-if": {
    "si": "ඔබේ විකල්ප තත්ත්වය සකසන්න",
    "ta": "உங்கள் மாற்றுச் சூழலை அமைக்கவும்"
  },
  "One cow · next day after its latest usable record": {
    "si": "එක් ගවයෙක් · අවසන් භාවිත කළ හැකි වාර්තාවට පසු දිනය",
    "ta": "ஒரு பசு · கடைசிப் பயன்படக்கூடிய பதிவுக்கு அடுத்த நாள்"
  },
  "Approved cow reference": {
    "si": "අනුමත ගව හැඳුනුම",
    "ta": "அங்கீகரிக்கப்பட்ட பசுக் குறிப்பு"
  },
  "Select below or paste an approved reference": {
    "si": "පහතින් තෝරන්න හෝ අනුමත හැඳුනුමක් ඇතුළු කරන්න",
    "ta": "கீழே தேர்ந்தெடுக்கவும் அல்லது அங்கீகரித்த குறிப்பை ஒட்டவும்"
  },
  "Load available cows": {
    "si": "ලබා ගත හැකි ගවයන් පෙන්වන්න",
    "ta": "கிடைக்கும் பசுக்களை ஏற்று"
  },
  "Loading cows…": {
    "si": "ගව තොරතුරු ලබා ගනිමින්…",
    "ta": "பசுக்களை ஏற்றுகிறது…"
  },
  "Available cows": {
    "si": "ලබා ගත හැකි ගවයන්",
    "ta": "கிடைக்கும் பசுக்கள்"
  },
  "Choose a cow": {
    "si": "ගවයෙකු තෝරන්න",
    "ta": "ஒரு பசுவைத் தேர்ந்தெடுக்கவும்"
  },
  "What would you change?": {
    "si": "ඔබ වෙනස් කරන්නේ කුමක්ද?",
    "ta": "எதை மாற்ற விரும்புகிறீர்கள்?"
  },
  "THI exposure": {
    "si": "THI නිරාවරණය",
    "ta": "THI வெளிப்பாடு"
  },
  "Milking frequency": {
    "si": "කිරි දෙවීම් වාර ගණන",
    "ta": "கறவை எண்ணிக்கை"
  },
  "THI and milking frequency together": {
    "si": "THI සහ කිරි දෙවීම් ගණන එකවර",
    "ta": "THI மற்றும் கறவை எண்ணிக்கை ஒன்றாக"
  },
  "Proposed THI": {
    "si": "යෝජිත THI",
    "ta": "முன்மொழியும் THI"
  },
  "Proposed milkings per day": {
    "si": "යෝජිත දෛනික කිරි දෙවීම් ගණන",
    "ta": "முன்மொழியும் தினசரி கறவை எண்ணிக்கை"
  },
  "Milkings per day": {
    "si": "දිනකට කිරි දෙවීම් ගණන",
    "ta": "தினசரி கறவை எண்ணிக்கை"
  },
  "Use absolute values, not percentages. Feed scenarios are unsupported. Training-range checks may withhold an estimate.": {
    "si": "ප්‍රතිශත වෙනුවට නිරපේක්ෂ අගයන් දෙන්න. ආහාර තත්ත්ව සහාය නොදක්වයි. පුහුණු පරාස පරීක්ෂණයෙන් ඇස්තමේන්තුවක් නොලැබිය හැක.",
    "ta": "சதவீதங்களுக்குப் பதிலாக முழுமையான மதிப்புகளைத் தரவும். தீவன மாற்றங்கள் ஆதரிக்கப்படவில்லை. பயிற்சி வரம்புச் சோதனையால் மதிப்பீடு நிறுத்தப்படலாம்."
  },
  "Run what-if": {
    "si": "අනුකරණය ක්‍රියාත්මක කරන්න",
    "ta": "மாற்றை உருவகப்படுத்து"
  },
  "Choose an approved cow reference.": {
    "si": "අනුමත ගව හැඳුනුමක් තෝරන්න.",
    "ta": "அங்கீகரிக்கப்பட்ட பசுக் குறிப்பைத் தேர்ந்தெடுக்கவும்."
  },
  "Enter a finite proposed THI value.": {
    "si": "වලංගු යෝජිත THI අගයක් දෙන්න.",
    "ta": "செல்லுபடியாகும் முன்மொழிந்த THI மதிப்பைத் தரவும்."
  },
  "Enter a positive proposed milking frequency.": {
    "si": "ධන කිරි දෙවීම් වාර ගණනක් දෙන්න.",
    "ta": "நேர்மறையான முன்மொழிந்த கறவை எண்ணிக்கையைத் தரவும்."
  },
  "What-if requests require a backend on this computer.": {
    "si": "අනුකරණයට මෙම පරිගණකයේ පසුපස සේවාවක් අවශ්‍යය.",
    "ta": "உருவகப்படுத்தலுக்கு இந்தக் கணினியில் பின்தளச் சேவை தேவை."
  },
  "No approved cows are available for simulation.": {
    "si": "අනුකරණයට අනුමත ගවයන් නොමැත.",
    "ta": "உருவகப்படுத்தலுக்கு அங்கீகரிக்கப்பட்ட பசுக்கள் கிடைக்கவில்லை."
  },
  "Available cows could not be loaded. Check the C2 API and local data permissions.": {
    "si": "ගව තොරතුරු ලබා ගත නොහැක. C2 සේවාව සහ දේශීය දත්ත අවසර පරීක්ෂා කරන්න.",
    "ta": "பசுக்களை ஏற்ற முடியவில்லை. C2 சேவையையும் உள்ளூர் தரவு அனுமதிகளையும் சரிபார்க்கவும்."
  },
  "Available cows could not be validated.": {
    "si": "ගව තොරතුරු තහවුරු කළ නොහැක.",
    "ta": "பசு விவரங்களைச் சரிபார்க்க முடியவில்லை."
  },
  "Check the scenario inputs.": {
    "si": "තත්ත්ව ආදාන පරීක්ෂා කරන්න.",
    "ta": "சூழல் உள்ளீடுகளைச் சரிபார்க்கவும்."
  },
  "Prediction horizon (days)": {
    "si": "පුරෝකථන කාලය (දින)",
    "ta": "முன்னறிவிப்புக் காலம் (நாட்கள்)"
  },
  "Observed milk yield": {
    "si": "වාර්තාගත කිරි ප්‍රමාණය",
    "ta": "பதிவான பால் அளவு"
  },
  "Predicted baseline yield": {
    "si": "මූලික තත්ත්වයේ පුරෝකථනය",
    "ta": "அடிப்படை முன்னறிவிப்பு அளவு"
  },
  "Predicted what-if yield": {
    "si": "විකල්ප තත්ත්වයේ පුරෝකථනය",
    "ta": "மாற்றுச் சூழல் முன்னறிவிப்பு அளவு"
  },
  "Predicted yield difference": {
    "si": "පුරෝකථන කිරි වෙනස",
    "ta": "முன்னறிவிப்பு பால் வேறுபாடு"
  },
  "Predicted change (%)": {
    "si": "පුරෝකථන වෙනස (%)",
    "ta": "முன்னறிவிப்பு மாற்றம் (%)"
  },
  "Scenario status": {
    "si": "තත්ත්ව ප්‍රතිඵලය",
    "ta": "சூழல் முடிவு நிலை"
  },
  "Training support": {
    "si": "පුහුණු දත්ත පරාසය",
    "ta": "பயிற்சித் தரவு ஆதரவு"
  },
  "Recorded feature inputs": {
    "si": "වාර්තාගත ආදාන",
    "ta": "பதிவான உள்ளீடுகள்"
  },
  "Your proposed inputs": {
    "si": "ඔබේ යෝජිත ආදාන",
    "ta": "நீங்கள் முன்மொழிந்த உள்ளீடுகள்"
  },
  "Operational feasibility validated": {
    "si": "මෙහෙයුම් හැකියාව තහවුරු කර ඇත",
    "ta": "செயல்படுத்தும் சாத்தியம் சரிபார்க்கப்பட்டது"
  },
  "Assumptions": {
    "si": "උපකල්පන",
    "ta": "அனுமானங்கள்"
  },
  "Local C2 simulation API": {
    "si": "දේශීය C2 අනුකරණ සේවාව",
    "ta": "உள்ளூர் C2 உருவகப்படுத்தல் சேவை"
  },
  "Within checked training support": {
    "si": "පරීක්ෂා කළ පුහුණු පරාසය තුළ",
    "ta": "சரிபார்த்த பயிற்சி வரம்பிற்குள்"
  },
  "Outside training support": {
    "si": "පුහුණු පරාසයෙන් පිටත",
    "ta": "பயிற்சி வரம்பிற்கு வெளியே"
  },
  "Training range unavailable": {
    "si": "පුහුණු පරාසය නොමැත",
    "ta": "பயிற்சி வரம்பு கிடைக்கவில்லை"
  },
  "Not assessed": {
    "si": "ඇගයීම කර නැත",
    "ta": "மதிப்பிடப்படவில்லை"
  },
  "Model-input what-if estimated": {
    "si": "ආකෘති ආදාන වෙනස ඇස්තමේන්තු කර ඇත",
    "ta": "மாதிரி உள்ளீட்டு மாற்றம் மதிப்பிடப்பட்டது"
  },
  "Prediction unavailable": {
    "si": "පුරෝකථනය නොමැත",
    "ta": "முன்னறிவிப்பு கிடைக்கவில்லை"
  },
  "Baseline feature unavailable": {
    "si": "මූලික ආදානය නොමැත",
    "ta": "அடிப்படை உள்ளீடு கிடைக்கவில்லை"
  },
  "Unsupported scenario meaning": {
    "si": "තත්ත්ව අර්ථය සහාය නොදක්වයි",
    "ta": "சூழலின் பொருள் ஆதரிக்கப்படவில்லை"
  },
  "Run a what-if simulation for {cow}: {changes}.": {
    "si": "{cow} සඳහා විකල්ප තත්ත්ව අනුකරණයක් කරන්න: {changes}.",
    "ta": "{cow} க்கான மாற்றுச் சூழலை உருவகப்படுத்துங்கள்: {changes}."
  },
  "Model what-if": {
    "si": "ආකෘති විකල්ප තත්ත්වය",
    "ta": "மாதிரி மாற்றுச் சூழல்"
  },
  "What-if simulation": {
    "si": "විකල්ප තත්ත්ව අනුකරණය",
    "ta": "மாற்றுச் சூழல் உருவகப்படுத்தல்"
  },
  "Ask a what-if question in chat": {
    "si": "සංවාදයේ විකල්ප තත්ත්ව ප්‍රශ්නයක් අසන්න",
    "ta": "உரையாடலில் மாற்றுச் சூழல் கேள்வியைக் கேளுங்கள்"
  },
  "Reply with the missing cow or scenario detail…": {
    "si": "අඩු ගව හැඳුනුම හෝ තත්ත්ව විස්තරය දෙන්න…",
    "ta": "விடுபட்ட பசுக் குறிப்பை அல்லது சூழல் விவரத்தைத் தரவும்…"
  },
  "Forecast date": {"si": "පුරෝකථනය අවශ්‍ය දිනය", "ta": "முன்னறிவிப்பு தேவைப்படும் தேதி"},
  "Review older records": {"si": "පැරණි වාර්තා බලන්න", "ta": "பழைய பதிவுகளைப் பார்க்கவும்"},
  "Past day to review (optional)": {"si": "බැලීමට අවශ්‍ය අතීත දිනය (විකල්ප)", "ta": "பார்க்க வேண்டிய கடந்த தேதி (விருப்பம்)"},
  "Leave blank to select a forecast automatically. For historical risk, choose the past day you want to review.": {"si": "පුරෝකථනය ස්වයංක්‍රීයව තේරීමට හිස්ව තබන්න. අතීත අවදානම සඳහා බැලීමට අවශ්‍ය දිනය තෝරන්න.", "ta": "முன்னறிவிப்பைத் தானாகத் தேர்ந்தெடுக்க காலியாக விடவும். கடந்தகால அபாயத்திற்கு பார்க்க வேண்டிய தேதியைத் தேர்ந்தெடுக்கவும்."},
  "Selected as of": {"si": "තේරීම සඳහා භාවිතා කළ දිනය", "ta": "தேர்வுக்குப் பயன்படுத்திய தேதி"},
  "Technical notes": {"si": "තාක්ෂණික සටහන්", "ta": "தொழில்நுட்பக் குறிப்புகள்"},
  "Technical source details": {"si": "මූලාශ්‍රයේ තාක්ෂණික විස්තර", "ta": "மூலத்தின் தொழில்நுட்ப விவரங்கள்"},
  "Historical research result. It cannot provide live alerts or confirm causes.": {"si": "අතීත පර්යේෂණ ප්‍රතිඵලයකි. සජීවී අනතුරු ඇඟවීම් හෝ හේතු තහවුරු කිරීම සඳහා භාවිතා කළ නොහැක.", "ta": "இது கடந்தகால ஆய்வு முடிவு. நேரடி எச்சரிக்கைகளை வழங்கவோ காரணங்களை உறுதிப்படுத்தவோ முடியாது."},
  "Development forecast. It has not been checked against your current records.": {"si": "සංවර්ධන පුරෝකථනයකි. ඔබේ වත්මන් වාර්තා සමඟ ගැළපීම පරීක්ෂා කර නැත.", "ta": "இது உருவாக்க நிலையில் உள்ள முன்னறிவிப்பு. உங்கள் தற்போதைய பதிவுகளுடன் பொருத்தம் சரிபார்க்கப்படவில்லை."},
  "Model-based what-if estimate. Actual outcomes may differ; feasibility has not been checked.": {"si": "ආකෘතියකින් ලැබුණු විකල්ප තත්ත්ව ඇස්තමේන්තුවකි. සැබෑ ප්‍රතිඵල වෙනස් විය හැක; ක්‍රියාත්මක කළ හැකිද යන්න පරීක්ෂා කර නැත.", "ta": "இது மாதிரி சார்ந்த மாற்றுச் சூழல் மதிப்பீடு. உண்மை முடிவுகள் மாறலாம்; செயல்படுத்தும் சாத்தியம் சரிபார்க்கப்படவில்லை."},
  "The forecast falls outside the supplied range and needs review.": {"si":"පුරෝකථනය ලබා දුන් පරාසයෙන් පිටතය. සමාලෝචනයක් අවශ්‍යය.","ta":"முன்னறிவிப்பு வழங்கப்பட்ட வரம்பிற்கு வெளியே உள்ளது; மீளாய்வு தேவை."}
,
  "Missing measurements are not filled in. Weekly changes are shown only when coverage supports comparison.": {"si": "අඩු මිනුම් පුරවන්නේ නැත. දත්ත ආවරණය සංසන්දනයට ප්‍රමාණවත් විට පමණක් සතිපතා වෙනස්කම් පෙන්වයි.", "ta": "விடுபட்ட அளவீடுகள் நிரப்பப்படவில்லை. தரவு முழுமை ஒப்பீட்டை ஆதரிக்கும் போது மட்டுமே வாராந்திர மாற்றங்கள் காட்டப்படுகின்றன."}
,
  "Milk summary chart and report": {"si": "කිරි සාරාංශ ප්‍රස්තාරය සහ වාර්තාව", "ta": "பால் சுருக்க வரைபடமும் அறிக்கையும்"}
,
  "YOUR RECORDED MILK": {"si": "ඔබේ වාර්තාගත කිරි", "ta": "உங்கள் பதிவான பால்"}
,
  "Daily milk and weekly comparison": {"si": "දෛනික කිරි සහ සතිපතා සංසන්දනය", "ta": "தினசரிப் பாலும் வாராந்திர ஒப்பீடும்"}
,
  "Historical records": {"si": "අතීත වාර්තා", "ta": "கடந்தகாலப் பதிவுகள்"}
,
  "Download Excel": {"si": "Excel වාර්තාව බාගන්න", "ta": "Excel அறிக்கையைப் பதிவிறக்கவும்"}
,
  "Preparing Excel…": {"si": "Excel වාර්තාව සකසමින්…", "ta": "Excel அறிக்கை தயாராகிறது…"}
,
  "Recorded milk (DelPro)": {"si": "වාර්තාගත කිරි (DelPro)", "ta": "பதிவான பால் (DelPro)"}
,
  "Milk shipments": {"si": "කිරි නැව්ගත කිරීම්", "ta": "பால் விநியோகப் பதிவுகள்"}
,
  "Not recorded": {"si": "වාර්තා වී නැත", "ta": "பதிவாகவில்லை"}
,
  "Latest period": {"si": "අවසන් කාලය", "ta": "கடைசி காலம்"}
,
  "Previous period": {"si": "පෙර කාලය", "ta": "முந்தைய காலம்"}
,
  "Comparison unavailable": {"si": "සංසන්දනය ලබා ගත නොහැක", "ta": "ஒப்பீடு கிடைக்கவில்லை"}
,
  "weekly change": {"si": "සතිපතා වෙනස", "ta": "வாராந்திர மாற்றம்"}
,
  "Milk recorded and milk shipped are separate measurements. They are not added together.": {"si": "වාර්තාගත කිරි සහ නැව්ගත කළ කිරි වෙන වෙනම මිනුම් වේ. එම අගයන් එකතු කර නැත.", "ta": "பதிவான பாலும் விநியோகித்த பாலும் தனித்தனி அளவீடுகள். இவை ஒன்றாகக் கூட்டப்படவில்லை."}
,
  "Daily milk chart in litres. Missing measurements are gaps.": {"si": "දෛනික කිරි ලීටර්වලින්. අඩු මිනුම් හිඩැස් ලෙස පෙන්වයි.", "ta": "தினசரிப் பால் லிட்டர்களில். விடுபட்ட அளவீடுகள் இடைவெளிகளாகக் காட்டப்படுகின்றன."}
,
  "No daily milk measurements were supplied for this period.": {"si": "මෙම කාලයට දෛනික කිරි මිනුම් ලබා දී නැත.", "ta": "இந்தக் காலத்திற்கான தினசரிப் பால் அளவீடுகள் வழங்கப்படவில்லை."}
,
  "Missing measurements appear as gaps, not zero. The dashed divider separates the previous and latest seven days. Flagged or incomplete periods cannot support a reliable weekly change.": {"si": "අඩු මිනුම් ශූන්‍ය ලෙස නොව හිඩැස් ලෙස පෙන්වයි. ඉරි සහිත සීමාව පෙර සහ අවසන් දින හත වෙන් කරයි. හිඩැස් හෝ අසම්පූර්ණ වාර්තා ඇති විට විශ්වාසදායක සතිපතා වෙනසක් ගණනය කළ නොහැක.", "ta": "விடுபட்ட அளவீடுகள் பூஜ்ஜியமாக அல்லாமல் இடைவெளிகளாகக் காட்டப்படுகின்றன. முறிந்த கோடு முந்தைய மற்றும் கடைசி ஏழு நாட்களைப் பிரிக்கிறது. குறிக்கப்பட்ட அல்லது முழுமையற்ற காலங்களிலிருந்து நம்பகமான வாராந்திர மாற்றத்தைக் கணக்கிட முடியாது."}
,
  "View daily figures": {"si": "දෛනික අගයන් බලන්න", "ta": "தினசரி மதிப்புகளைக் காண்க"}
,
  "Daily figures used in this answer and download": {"si": "මෙම පිළිතුර සහ බාගත කිරීම සඳහා භාවිතා කළ දෛනික අගයන්", "ta": "இந்தப் பதிலிலும் பதிவிறக்கத்திலும் பயன்படுத்திய தினசரி மதிப்புகள்"}
,
  "Date": {"si": "දිනය", "ta": "தேதி"}
,
  "Record status": {"si": "වාර්තා තත්ත්වය", "ta": "பதிவு நிலை"}
,
  "Day not recorded": {"si": "දිනය වාර්තා වී නැත", "ta": "நாள் பதிவாகவில்லை"}
,
  "Data gap flagged": {"si": "දත්ත හිඩැසක් සලකුණු කර ඇත", "ta": "தரவு இடைவெளி குறிக்கப்பட்டுள்ளது"}
,
  "Gap status unknown": {"si": "හිඩැස් තත්ත්වය නොදනී", "ta": "இடைவெளி நிலை தெரியவில்லை"}
,
  "Recorded": {"si": "වාර්තාගත", "ta": "பதிவாகியுள்ளது"}
,
  "The Excel download failed. Your saved answer is unchanged. Try again.": {"si": "Excel බාගත කිරීම අසාර්ථක විය. සුරැකි පිළිතුර වෙනස් වී නැත. නැවත උත්සාහ කරන්න.", "ta": "Excel பதிவிறக்கம் தோல்வியடைந்தது. சேமித்த பதில் மாறவில்லை. மீண்டும் முயற்சிக்கவும்."}
};
export function t(language: Language, text: string): string { return language === 'en' ? text : catalog[text]?.[language] ?? text; }

/** Interpolate only supplied labels/counts; never translate stored evidence values. */
export function message(language: Language, key: string, values: Record<string,string|number>): string {
  return t(language,key).replace(/\{(\w+)\}/g, (token,key: string) => Object.prototype.hasOwnProperty.call(values,key) ? String(values[key]) : token);
}
