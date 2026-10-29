from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


STUDENT_BOOK_SECTIONS = [
    {
        'title': 'উদ্ভিদবিজ্ঞান',
        'subtitle': 'Botany · All Chapters',
        'icon': '❀',
        'theme': 'botany',
        'chapters': [
            ('কোষ ও এর গঠন', 'https://drive.google.com/file/d/1vR3JzTvJAvj7rwSiqzmPQEpUHxsqfeel/view'),
            ('কোষ বিভাজন', 'https://drive.google.com/file/d/1FcSRFoROnZsOr29dnSEvUaJBOxP_6Awy/view?usp=sharing'),
            ('কোষ রসায়ন', 'https://drive.google.com/file/d/1zJZ8V9sPLUlx4m1wUJcTAdez1bjtOP6I/view'),
            ('অণুজীব', 'https://drive.google.com/file/d/1jm40P9zT8q2IrBKn1Z8AugvZOzPcVBSZ/view'),
            ('শৈবাল ও ছত্রাক', 'https://drive.google.com/file/d/1BFKbNq0Jwp-EtAjrWfPnhHg5i_AkPMrN/view'),
            ('ব্রায়োফাইটা ও টেরিডোফাইটা', 'https://drive.google.com/file/d/1w5D2UZzzziFyt7dOO_im2apx-ReyhUmD/view'),
            ('নগ্নবীজী ও আবৃতবীজী উদ্ভিদ', 'https://drive.google.com/file/d/1Yb2rvP0uG2dGYj3efulBmUqUZHLBTIyj/view'),
            ('টিসু ও টিস্যুতন্ত্র', 'https://drive.google.com/file/d/1gZ9OeQh41AlgZ2IloqrG5zZxPGy_PaHw/view'),
            ('উদ্ভিদ শারীরতত্ত্ব', 'https://drive.google.com/file/d/1K2pqzdZ1Tf25F3d_CRp-w3r_3QFwB0lB/view'),
            ('উদ্ভিদ প্রজনন', 'https://drive.google.com/file/d/125DCVxwu9T36IC2o6xOk5pSdTgAiEo__/view'),
            ('জীবপ্রযুক্তি', 'https://drive.google.com/file/d/1z3_0YBImdclzwCJNn8ot0iYlCDWAP4VJ/view'),
            ('জীবের পরিবেশ', 'https://drive.google.com/file/d/15PJJfeNNQdc5U2TSedmpPh4KxzAb8mLV/view'),
        ],
    },
    {
        'title': 'প্রাণিবিজ্ঞান',
        'subtitle': 'Zoology · All Chapters',
        'icon': '♧',
        'theme': 'zoology',
        'chapters': [
            ('প্রাণীর বিভিন্নতা ও শ্রেণিবিন্যাস', 'https://drive.google.com/file/d/1GzVd2MNC67xUuLrG11gES5Phl03S9UCL/view'),
            ('প্রাণীর পরিচিতি', 'https://drive.google.com/file/d/17nk6rHcvDj95DFBv8jCH6Jgx-HBFBOKz/view'),
            ('পরিপাক ও শোষণ', 'https://drive.google.com/file/d/1lkmpB0h54KT2kN26cRauZAHNMEPOdyag/view'),
            ('রক্ত ও সংবহন', 'https://drive.google.com/file/d/1t4QdJ9B4yfDb4xqk7J7hPr4T8w20Z3TX/view'),
            ('শ্বসন ও শ্বাসক্রিয়া', 'https://drive.google.com/file/d/14KzEHufGmK_2DuJAah-lxwfbKGcqEEu1/view'),
            ('বর্জ্য ও নিষ্কাশন', 'https://drive.google.com/file/d/1JO4YmheksNoEKjN5d15I4nrljR6wc2tZ/view'),
            ('চলন ও অঙ্গচালনা', 'https://drive.google.com/file/d/1TsCiSmHrARGURYTHwswdj4a2cjreaRSJ/view'),
            ('সমন্বয় ও নিয়ন্ত্রণ', 'https://drive.google.com/file/d/1RDGmjpBywAL6l6j0ZTG6H2RLvxoLnQWq/view'),
            ('মানব জীবনের ধারাবাহিকতা', 'https://drive.google.com/file/d/1ZcJmirQ9RbEjn_RXasTFAFQztn8ZwGl2/view'),
            ('মানবদেহের প্রতিরক্ষা', 'https://drive.google.com/file/d/1jraQBetrmAR0wDtVhKJazA-6p30Flnw-/view'),
            ('জিনতত্ত্ব ও বিবর্তন', 'https://drive.google.com/file/d/11_7c9va59g8AsuBzsJUDklQVzV2hqhhM/view'),
            ('প্রাণীর আচরণ', 'https://drive.google.com/file/d/1kX8OrCE-Lyz18VPN4uzTZMev9lwiuqEW/view'),
        ],
    },
    {
        'title': 'পদার্থবিজ্ঞান',
        'subtitle': 'Physics · ১ম পত্র',
        'icon': '⌁',
        'theme': 'physics',
        'chapters': [
            ('ভৌতজগৎ ও পরিমাপ (Physical World and Measurement)', 'https://drive.google.com/file/d/1MUKde7R83N8GAbHBMx6N-Yu2b--l67dJ/view'),
            ('ভেক্টর (Vector)', 'https://drive.google.com/file/d/1Pa9kxnhPLZmbf3lHNLptQU4MJsVbR0aV/view'),
            ('গতিবিদ্যা (Dynamics)', 'https://drive.google.com/file/d/1CH9ZPI8baU1TJF7QVwWn6Fw1l-SCvj4H/view'),
            ('নিউটনীয় বলবিদ্যা (Newtonian Mechanics)', 'https://drive.google.com/file/d/1wLLZME5I_QOC_FyICOlhd4g-Bs2bNeqF/view'),
            ('কাজ (Work, Energy and Power)', 'https://drive.google.com/file/d/1M5XFatSu9Ujp411wXsmyn9QI7hTIw56R/view'),
            ('মহাকর্ষ ও অভিকর্ষ (Gravity and Gravitation)', 'https://drive.google.com/file/d/1JbacDKeVvSDl3QnFIP2AQFai64WVgQlO/view'),
            ('পদার্থের গাঠনিক ধর্ম (Structural Properties of Matter)', 'https://drive.google.com/file/d/16WkgbeLbbVvl88OTAA-9LCXay33-Xifg/view'),
            ('পর্যাবৃত্তি গতি (Periodic Motion)', 'https://drive.google.com/file/d/1PAKAM2DrbF9V8eMZgLeQNB1xF3lk3jlj/view'),
            ('তরঙ্গ (Waves)', 'https://drive.google.com/file/d/1xoqLRTes8GJYk0WHKzq_cki1ZlCxXp2-/view'),
            ('আদর্শ গ্যাস ও গ্যাসের গতিতত্ত্ব (Ideal Gas and Kinetic Theory of Gases)', 'https://drive.google.com/file/d/1kADDegt0u7C-HSYkCGoUe8zIj2l5VvuU/view'),
        ],
    },
    {
        'title': 'পদার্থবিজ্ঞান',
        'subtitle': 'Physics · ২য় পত্র',
        'icon': '⌁',
        'theme': 'physics',
        'chapters': [
            ('তাপগতিবিদ্যা (Thermodynamics)', None),
            ('স্থির তড়িৎ (Static Electricity)', 'https://drive.google.com/file/d/12oclM4wnLUHGfX2GoZN2AfgtK3SPhO3n/view'),
            ('চল তড়িৎ (Current Electricity)', 'https://drive.google.com/file/d/1AGSCwLRC-Fyu1_hC76yMyPw7kgy4O3pn/view'),
            ('তড়িৎ প্রবাহের চৌম্বক ক্রিয়া ও চুম্বকত্ব', 'https://drive.google.com/file/d/1hvO9OE4oCOL9548C7YfYtXgPraHCrlmi/view'),
            ('তড়িৎ চৌম্বক আবেশ ও পরিবর্তী প্রবাহ', 'https://drive.google.com/file/d/1daAdVmwLUWgSF3fyTi6sJBnepGZX4kty/view'),
            ('জ্যামিতিক আলোকবিজ্ঞান', 'https://drive.google.com/file/d/1XDNRvMEREt5K-mZIp3Xt5Wd9FCKT3Nya/view'),
            ('ভৌত আলোকবিজ্ঞান', 'https://drive.google.com/file/d/1tKjG8etEpnFwgtfAcCYaI7lPPY4tKcST/view'),
            ('আধুনিক পদার্থবিজ্ঞানের সূচনা', 'https://drive.google.com/file/d/14sNqBZVJ9Uct3b8Kjam_lrU4OK9g5dOS/view'),
            ('পরমাণুর মডেল এবং নিউক্লিয়ার পদার্থবিজ্ঞান', 'https://drive.google.com/file/d/127DzGwDS61uxBdZN8l0efKH00XP5mmNU/view'),
            ('সেমিকন্ডাক্টর ও ইলেকট্রনিকস', 'https://drive.google.com/file/d/12euP_ZEffpCGbhewcGdc6kYYI6s9s5nU/view'),
            ('জ্যোতির্বিজ্ঞান', 'https://drive.google.com/file/d/154md7P0xe906mpmrWbM3_CCeoYI8wWZC/view'),
        ],
    },
    {
        'title': 'রসায়ন',
        'subtitle': 'Chemistry · ১ম পত্র',
        'icon': '⚗',
        'theme': 'chemistry',
        'chapters': [
            ('ল্যাবরেটরির নিরাপদ ব্যবহার', 'https://drive.google.com/file/d/1QpOYOh5pzVhCpN7pcfVndhzp5JjBJdIA/view'),
            ('গুণগত রসায়ন', 'https://drive.google.com/file/d/1icMVDMx-8CASypEiJM4oMbAf8AGQnLK4/view'),
            ('মৌলের পর্যায়বৃত্ত ধর্ম ও রাসায়নিক বন্ধন', 'https://drive.google.com/file/d/1Ty6fZGcvgIby_Agrlvt-THr1SpSv3VFE/view'),
            ('রাসায়নিক পরিবর্তন', 'https://drive.google.com/file/d/1y73db7v7T-F0nSHLwHMMySFPFhqQkj7p/view'),
            ('কর্মমুখী রসায়ন', 'https://drive.google.com/file/d/1IBG3fvPOJ8bJUKBCSD4Os5GP44nDvdCV/view'),
        ],
    },
    {
        'title': 'রসায়ন',
        'subtitle': 'Chemistry · ২য় পত্র',
        'icon': '⚗',
        'theme': 'chemistry',
        'chapters': [
            ('পরিবেশ রসায়ন', 'https://drive.google.com/file/d/1ChLbN3RVLyy5z-581-NrlFCBsq2BDkE2/view'),
            ('জৈব রসায়ন', 'https://drive.google.com/file/d/1V0ucotkX_z8bRN_o4TGpQ0jtehuc-ERE/view'),
            ('পরিমাণগত রসায়ন', 'https://drive.google.com/file/d/1JELuS2BuYaCS2lF2oCRNxrNAcI-fCQZA/view'),
            ('তড়িৎ রসায়ন', 'https://drive.google.com/file/d/15mkVJUKfYHt0NOV0YGq9-9Hi6jRGmqJG/view'),
            ('অর্থনৈতিক রসায়ন', 'https://drive.google.com/file/d/1UnZ-pAXgz6_aIG5bk2t8uDu6KBWGlZrG/view'),
        ],
    },
]


def mobile_pdf_preview_url(view_url):
    if not view_url:
        return view_url
    parsed_url = urlsplit(view_url)
    path_parts = parsed_url.path.strip('/').split('/')
    if (
        parsed_url.scheme == 'https'
        and parsed_url.netloc == 'drive.google.com'
        and len(path_parts) == 4
        and path_parts[:2] == ['file', 'd']
        and path_parts[3] == 'view'
    ):
        resource_keys = parse_qs(parsed_url.query).get('resourcekey', [])
        query = urlencode({'resourcekey': resource_keys[0]}) if resource_keys else ''
        return urlunsplit((
            'https',
            'drive.google.com',
            f'/file/d/{path_parts[2]}/preview',
            query,
            '',
        ))
    return view_url
