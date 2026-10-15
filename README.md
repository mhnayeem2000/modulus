# Modulus Edu · কোচিং ম্যানেজার

Django-ভিত্তিক কোচিং ব্যবস্থাপনা অ্যাপ। সুপার অ্যাডমিন, শিক্ষক ও শিক্ষার্থীর জন্য আলাদা লগইন-সুরক্ষিত ড্যাশবোর্ড রয়েছে।

## চালু করা

প্রজেক্টের ভার্চুয়াল এনভায়রনমেন্ট সক্রিয় করে `modulus` ফোল্ডার থেকে চালান:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

তারপর `http://127.0.0.1:8000/`-এ লগইন করুন। সুপারইউজারই সুপার অ্যাডমিন; তিনি ড্যাশবোর্ডের **শিক্ষকবৃন্দ** পাতায় শিক্ষকের অ্যাকাউন্ট তৈরি ও মাসভিত্তিক ক্লাস-পরীক্ষার হিসাব দেখতে পারবেন। শিক্ষার্থী যোগ এবং শিক্ষার্থীর লগইন তৈরির অনুমতি শুধু সুপার অ্যাডমিনের। অ্যাপে উন্মুক্ত সাইন-আপ নেই।

## cPanel deployment

Passenger setup, production environment variables, MySQL/SQLite configuration, static collection, and safe data transfer instructions are in [CPANEL_DEPLOYMENT.md](CPANEL_DEPLOYMENT.md).

### WhatsApp Cloud API configuration

Meta থেকে আগে প্রকাশিত হয়ে থাকতে পারে এমন access token revoke/rotate করুন। নতুন token source control, code, browser বা logs-এ রাখবেন না। Local development-এ project root-এর ignored `.env` file-এ রাখুন:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env` file-এর `WHATSAPP_ACCESS_TOKEN`-এ নতুন Meta token এবং `WHATSAPP_PHONE_NUMBER_ID`-এ Meta Phone Number ID বসান। OS environment variable থাকলে সেটি `.env` value-কে override করবে।

Meta WhatsApp Manager-এ `en` ভাষার `present_notice` এবং `absent_notice` **approved Utility** template থাকতে হবে। বর্তমান integration `present_notice`-এ শিক্ষার্থীর নাম ও তারিখ এবং `absent_notice`-এ শুধু শিক্ষার্থীর নাম পাঠায়। Meta-এর template approval এবং অভিভাবকের WhatsApp opt-in ছাড়া production message পাঠানো যাবে না। Attendance সংরক্ষণের সময় dashboard থেকে WhatsApp বা SMS নির্বাচন করা যায়। WhatsApp-এর late template configure না থাকায় late status-এ WhatsApp message পাঠানো হয় না; dashboard-এ এ বিষয়ে warning দেখায়। API-এর success response-কে “Meta accepted” হিসেবে track করা হয়; delivered/read নিশ্চিত করতে আলাদা Meta webhook configure করতে হবে। ব্যর্থ request database-এ থেকে যায়; production-এ `retry_whatsapp_attendance` command-টি Windows Task Scheduler/hosting scheduler দিয়ে নির্দিষ্ট বিরতিতে চালান।

### BulkSMSBD SMS configuration

BulkSMSBD account থেকে API key নিয়ে project root-এর `.env` file-এর `BULKSMSBD_API_KEY`-এ বসান:

```powershell
python manage.py migrate
python manage.py runserver
```

`.env` local development credential-এর জন্য; production-এ host-এর secret/environment configuration ব্যবহার করুন। `.env` Git-এ ignore করা হয়; `.env.example`-এ কোনো secret নেই। SMS API-তে `.env`-এর `BULKSMSBD_SENDER_ID` পাঠানো হয়; default হলো `8809617643378`। Sender-এ এই নম্বর দেখানোর জন্য BulkSMSBD-কে account-এ এই numeric sender/CLI non-masking route-এ register ও enable করতে হবে। API account-এ ওই sender ID configure না থাকলে `is_masking on null` error provider-এ হবে; code সেটি account-এ তৈরি করতে পারে না।

`Attempt to read property "is_masking" on null` BulkSMSBD server-এর account-side sender configuration error; Django-এর SMS payload পরিবর্তন করে provider-এর account setup ঠিক করা যাবে না। BulkSMSBD support-কে বলুন: “Please register/enable `8809617643378` as my numeric non-masking sender/CLI, and confirm this sender ID is enabled for my API account.” API গ্রহণ নিশ্চিত করলেই SMS-কে sent হিসেবে track করা হয়; delivery receipt পেতে provider-এর আলাদা callback/report integration লাগতে পারে।

Attendance page-এর **ব্যালেন্স দেখুন** button server থেকে BulkSMSBD balance API call করে; API key browser-এ পাঠানো বা দেখানো হয় না। SMS পাঠানোর আগে ও পরে balance তুলনা করে save alert-এ ওই save-এর আনুমানিক খরচ এবং পরের balance দেখানো হয়। অন্য কোনো app বা user একই account-এ একসঙ্গে SMS পাঠালে এই পার্থক্যটি নিখুঁত per-message charge নাও হতে পারে।

সুপার অ্যাডমিন sidebar-এর **SMS রিপোর্ট** page-এ recipient ও শিক্ষার্থী অনুযায়ী গৃহীত/ব্যর্থ SMS count, প্রতিটি SMS-এর status/attempt/provider ID বা error, এবং save অনুযায়ী balance ও মাপা আনুমানিক খরচ দেখা যায়। Attendance list-এ বর্তমান status-এর SMS BulkSMSBD গ্রহণ করলে ছোট tick দেখায়। `AttendanceSMSBatch`-এ প্রতিটি SMS save-এর summary রাখা হয়; পুরোনো notification-এর প্রাপক নম্বর migration-এ snapshot করা হয়।

সুপার অ্যাডমিন sidebar-এর **SMS System** page থেকে BulkSMSBD SMS globally ON/OFF করা যায়। OFF থাকলে attendance save হবে, কিন্তু SMS provider-এ কোনো request যাবে না; WhatsApp selection-এ এই switch প্রভাব ফেলে না। Setting database-এ থাকে এবং নতুন install-এ compatibility-র জন্য default ON।

পরীক্ষার নম্বর প্রথমবার save হলে বা পরিবর্তন হলে SMS System ON থাকলে অভিভাবকের নম্বরে `প্রিয় অভিভাবক, আপনার {Student Name} {Subject} {Paper} Paper {Chapter} Chapter {Marks}/{Total Marks} পেয়েছে। Rank: {Rank}/{Total} -Modulus Edu` format-এ সর্বোচ্চ ১৬০ character-এর SMS যায়। বিষয়, পত্র ও অধ্যায় পরীক্ষার নির্বাচিত field থেকে নেওয়া হয়; কোনো বিষয়ের নাম না থাকলে ভুল/অস্পষ্ট SMS না পাঠিয়ে রিপোর্টে ব্যর্থতার কারণ দেখায়। বিদ্যমান পরীক্ষা তালিকার **বিবরণ সংশোধন** দিয়ে বিষয়, পত্র ও অধ্যায় ঠিক করা যায়। ১৬০ character সীমা রাখতে প্রয়োজন হলে student, subject, paper বা chapter-এর নাম ছোট করা হয়; নম্বর, rank ও signature অক্ষুণ্ণ থাকে। একই marks আবার save করলে duplicate যায় না; আগের send ব্যর্থ হলে একই marks save-এ retry হয়। পরীক্ষার marks SMS-এর পাঠানোর status, rank ও attempt-ও SMS রিপোর্টে থাকে।

## অ্যাপের অংশ

- **সুপার অ্যাডমিন:** শিক্ষার্থী যোগ ও শিক্ষার্থীদের চূড়ান্ত উপস্থিতি নথিভুক্ত করা, শিক্ষক উপস্থিতি সরাসরি নথিভুক্ত/অনুমোদন করা, শিক্ষকভিত্তিক মাসিক ক্লাস সংখ্যা, পড়ানো ব্যাচ ও অধ্যায়, নেওয়া পরীক্ষা এবং অধ্যায়ভিত্তিক হিসাব। শিক্ষক রিপোর্টে ১ম/২য় বর্ষের tab থাকে; রুটিনে বর্ষ আলাদাভাবে বেছে নিয়ে ১ম/২য় বর্ষের tab-এ সাপ্তাহিক কার্ড দেখা যায়। পুরোনো রুটিনে বর্ষ বোঝা না গেলে নাম থেকে শনাক্ত করার চেষ্টা হয়; বাকি ক্ষেত্রে ১ম বর্ষে রাখা হয়, সম্পাদনায় ২য় বর্ষে সরানো যায়। প্রতিটি ক্লাস ১.৫ ঘণ্টা; সাধারণ ক্লাস বিকেল ৩টা–৭টা এবং রিভিশন ক্লাস ২টা–৩টার মধ্যে শুরু হয়। তিনিই শিক্ষকদের জন্য সাপ্তাহিক রুটিন তৈরি ও পরিচালনা করেন।
- **শিক্ষক:** শিক্ষার্থীদের তথ্য দেখা, পরের ক্লাসের রিমাইন্ডার, সুপার অ্যাডমিন অনুমোদিত তারিখের ক্যালেন্ডার ও নিজের যাচাইকৃত মাসিক উপস্থিতির হিসাব দেখা, নির্ধারিত ক্লাসে নিজের উপস্থিতির আবেদন করা, তারিখভিত্তিক সম্পন্ন ক্লাসের লগ এবং মাসিক ক্লাস/পরীক্ষার হিসাব দেখা, শিক্ষার্থীদের জন্য ফাইল প্রকাশ। ক্লাস ও পরীক্ষার রিপোর্ট ১ম/২য় বর্ষের tab-এ আলাদা করা হয়।
- **শিক্ষার্থী:** ড্যাশবোর্ডে আগামীকালের সব ক্লাস ও চলতি সপ্তাহের পরীক্ষা দেখবে; রুটিন, পরীক্ষা, ফলাফল, উপস্থিতি ও নম্বরের পরিসংখ্যান, ক্লাস শিট, বই এবং জরুরি ফাইল আলাদা বিভাগে থাকবে। নিজের অগ্রগতি পাতায় ছয় মাসের উপস্থিতি, অনুষ্ঠিত পরীক্ষার ফল/অনুপস্থিত ফল এবং বিষয়-পত্রভিত্তিক নম্বরের পরিবর্তন দেখা যায়।
- **সাপ্তাহিক রুটিন:** সুপার অ্যাডমিন সব ব্যাচের রুটিন যোগ, সম্পাদনা ও মুছতে পারবেন। শিক্ষক নিজের ক্লাসগুলোই তিন-কলামের সপ্তাহভিত্তিক ছকে দেখবেন; শিক্ষার্থী নিজের ব্যাচের সব ক্লাস দেখবে। আগামীকালের ক্লাস ও এই সপ্তাহের পরীক্ষা শিক্ষার্থীর ড্যাশবোর্ডে ভাসমান মনে করিয়ে দেওয়ার বার্তাতেও দেখানো হয়।
- **শিক্ষার্থীদের মতামত:** শিক্ষার্থীর পাঠানো মতামত শুধু সুপার অ্যাডমিন দেখতে পারবেন; সুপার অ্যাডমিন ড্যাশবোর্ডের মতামত বিভাগে সব জমা দেখতে পারবেন।
- **পাঠযোগ্যতা ও থিম:** বড় ও স্পষ্ট লেখার পাশাপাশি ড্যাশবোর্ড থেকে লাইট/ডার্ক মোড বেছে নেওয়া যায়; পছন্দটি একই ব্রাউজারে সংরক্ষিত থাকে।
- **শিক্ষার্থী ব্যবস্থাপনা:** নাম, আলাদা আইডি, ১ম/২য় বর্ষের dropdown batch এবং যোগাযোগের নম্বর যোগ/খোঁজা; migration পুরোনো batch নাম থেকে বর্ষ শনাক্তের চেষ্টা করে, অস্পষ্ট নাম ১ম বর্ষে রাখে—প্রয়োজনে সুপার অ্যাডমিন শিক্ষার্থীর তথ্য থেকে বর্ষ ঠিক করবেন। শিক্ষক ও সুপার অ্যাডমিন শিক্ষার্থীর নাম থেকে বিস্তারিত দেখতে পারেন, লগইন করা শিক্ষার্থী শুধু নিজের অগ্রগতি দেখতে পারে।
- **শিক্ষার্থীদের উপস্থিতি:** তারিখ ধরে উপস্থিত, অনুপস্থিত বা দেরিতে আসা শুধু সুপার অ্যাডমিন নথিভুক্ত ও সম্পাদনা করতে পারবেন।
- **WhatsApp উপস্থিতি নোটিফিকেশন:** উপস্থিতি সংরক্ষণের পর নতুন/পরিবর্তিত উপস্থিত বা অনুপস্থিত অবস্থার জন্য শিক্ষার্থীর অভিভাবককে Meta WhatsApp Cloud API-তে approved template দিয়ে জানানো হয়। অভিভাবকের নম্বর শিক্ষার্থীর তথ্য সম্পাদনার `অভিভাবকের WhatsApp নম্বর` ঘরে রাখতে হবে; এটি শিক্ষার্থীর নিজের `মোবাইল নম্বর` থেকে আলাদা। Meta API request গ্রহণ করলে notification record-এ message ID ও accepted state রাখা হয়; একই attendance/status বারবার save করলে duplicate পাঠানো হয় না। ব্যর্থ notification আবার পাঠাতে `python manage.py retry_whatsapp_attendance` চালান।
- **শিক্ষক উপস্থিতি:** সুপার অ্যাডমিন সরাসরি উপস্থিতি যাচাই/নথিভুক্ত করতে পারবেন। শিক্ষক নিজের নির্ধারিত ক্লাসের দিনে উপস্থিতির আবেদন করতে পারবেন; অনুমোদনের আগে তা গণনায় ধরা হবে না।
- **পাঠ্যক্রম dropdown:** রুটিন, পরিচালিত ক্লাস, শিক্ষাসামগ্রী ও পরীক্ষার ফর্মে একই HSC Science subject list ব্যবহৃত হয়; বিষয় বাছলে সেই বিষয়ের পত্র, আর পত্র বাছলে সেই পত্রের অধ্যায় dropdown-এ আসে। Server-side form validation-ও একই mapping মেনে চলে। অধ্যায়ের HSC 2027 তালিকাটি প্রচলিত textbook-ভিত্তিক provisional mapping—চূড়ান্ত NCTB syllabus/book edition-এর সঙ্গে মিলিয়ে নেওয়া প্রয়োজন।
- **পরীক্ষা ও ফলাফল:** পরীক্ষা ১ম/২য় বর্ষের সঙ্গে যুক্ত হয়; বিষয়, পত্র ও অধ্যায় dropdown থেকে নেওয়া, সংশ্লিষ্ট বর্ষের শিক্ষার্থীদের নম্বর দেওয়া ও সংশোধন করা যায়।
- **শিক্ষাসামগ্রী:** শিক্ষক PDF, Word/Office নথি বা ছবি আপলোড করতে পারেন; সর্বোচ্চ ফাইল ২০ MB। ফাইল শিক্ষার্থীর ব্যাচ অনুযায়ী সীমাবদ্ধ থাকে এবং লগইন ছাড়া ডাউনলোড করা যায় না। বই/বাহ্যিক লিংক নতুন tab-এ খোলে।
- **ব্র্যান্ডিং ও UI:** সব ড্যাশবোর্ড এবং লগইন পেজে Modulus Edu-এর লোগো দেখানো হয়; বর্ষভিত্তিক tab-গুলো responsive segmented control হিসেবে সাজানো।

## যাচাই

```powershell
python manage.py test students attendance exams portal
```
