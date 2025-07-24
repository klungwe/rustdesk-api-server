# cython:language_level=3
from pathlib import Path
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib import auth
from api.models import RustDeskPeer, RustDesDevice, UserProfile, ShareLink, ConnLog, FileLog, GithubRun
from django.forms.models import model_to_dict
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.conf import settings
from django.utils import timezone
from itertools import chain
from django.db.models.fields import DateTimeField, DateField, CharField, TextField
import datetime
from django.db.models import Model
import json
import time
import hashlib
import sys
from dateutil import tz
import platform
import psutil
import os

from io import BytesIO
import xlwt
from django.utils.translation import gettext as _
from .forms import AddPeerForm, EditPeerForm, AssignPeerForm

BASE_DIR = Path(__file__).resolve().parent.parent
salt = 'xiaomo'
EFFECTIVE_SECONDS = 7200

def getStrMd5(s):
    if not isinstance(s, (str,)):
        s = str(s)

    myHash = hashlib.md5()
    myHash.update(s.encode())

    return myHash.hexdigest()

def model_to_dict2(instance, fields=None, exclude=None, replace=None, default=None):
    """
    :params instance: Model object, not the QuerySet data set
    :params fields: Specify the field data to be displayed,('Field 1','Field 2')
    :params exclude: Specify the field data that is eliminated,('Field 1','Field 2')
    :params replace: Modify the field name to the required name,{'Database field name':'Front -end display name'}
    :params default: Added no existing field data,{'Field':'data'}
    """
    # 对传递进来的模型对象校验
    if not isinstance(instance, Model):
        raise Exception(_('model_to_dict接收的参数必须是模型对象'))
    # 对替换数据库字段名字校验
    if replace and type(replace) == dict:
        for replace_field in replace.values():
            if hasattr(instance, replace_field):
                raise Exception(_(f'model_to_dict,要替换成{replace_field}字段已经存在了'))
    # 对要新增的默认值进行校验
    if default and type(default) == dict:
        for default_key in default.keys():
            if hasattr(instance, default_key):
                raise Exception(_(f'model_to_dict,要新增默认值，但字段{default_key}已经存在了'))
    opts = instance._meta
    data = {}
    for f in chain(opts.concrete_fields, opts.private_fields, opts.many_to_many):
        # 源码下：这块代码会将时间字段剔除掉，我加上一层判断，让其不再剔除时间字段
        if not getattr(f, 'editable', False):
            if type(f) == DateField or type(f) == DateTimeField:
                pass
            else:
                continue
        # 如果fields参数传递了，要进行判断
        if fields is not None and f.name not in fields:
            continue
        # 如果exclude 传递了，要进行判断
        if exclude and f.name in exclude:
            continue

        key = f.name
        # 获取字段对应的数据
        if type(f) == DateTimeField:
            # 字段类型是，DateTimeFiled 使用自己的方式操作
            value = getattr(instance, key)
            value = datetime.datetime.strftime(value, '%Y-%m-%d %H:%M')
        elif type(f) == DateField:
            # 字段类型是，DateFiled 使用自己的方式操作
            value = getattr(instance, key)
            value = datetime.datetime.strftime(value, '%Y-%m-%d')
        elif type(f) == CharField or type(f) == TextField:
            # 字符串数据是否可以进行序列化，转成python结构数据
            value = getattr(instance, key)
            try:
                value = json.loads(value)
            except Exception as _:
                value = value
        else:#其他类型的字段
            # value = getattr(instance, key)
            key = f.name
            value = f.value_from_object(instance)
            # data[f.name] = f.value_from_object(instance)
        # 1、替换字段名字
        if replace and key in replace.keys():
            key = replace.get(key)
        data[key] = value
    #2、新增默认的字段数据
    if default:
        data.update(default)
    return data


def index(request):
    print('sdf',sys.argv)
    if request.user and request.user.username!='AnonymousUser':
        return HttpResponseRedirect('/api/work')
    return HttpResponseRedirect('/api/user_action?action=login')


def user_action(request):
    action = request.GET.get('action', '')
    if action == 'login':
        return user_login(request)
    elif action == 'register':
        return user_register(request)
    elif action == 'logout':
        return user_logout(request)
    else:
        return

def user_login(request):
    if request.method == 'GET':
        return render(request, 'login.html')

    username = request.POST.get('account', '')
    password = request.POST.get('password', '')
    if not username or not password:
        return JsonResponse({'code':0, 'msg':_('出了点问题，未获取用户名或密码。')})

    user = auth.authenticate(username=username,password=password)
    if user:
        auth.login(request, user)
        return JsonResponse({'code':1, 'url':'/api/work'})
    else:
        return JsonResponse({'code':0, 'msg':_('帐号或密码错误！')})

def user_register(request):
    info = ''
    if request.method == 'GET':
        return render(request, 'reg.html')
    ALLOW_REGISTRATION = settings.ALLOW_REGISTRATION
    result = {
        'code':0,
        'msg':''
    }
    if not ALLOW_REGISTRATION:
        result['msg'] = _('当前未开放注册，请联系管理员！')
        return JsonResponse(result)

    username = request.POST.get('user', '')
    password1 = request.POST.get('pwd', '')

    if len(username) <= 3:
        info = _('用户名不得小于3位')
        result['msg'] = info
        return JsonResponse(result)

    if len(password1)<8 or len(password1)>20:
        info = _('密码长度不符合要求, 应在8~20位。')
        result['msg'] = info
        return JsonResponse(result)

    user = UserProfile.objects.filter(Q(username=username)).first()
    if user:
        info = _('用户名已存在。')
        result['msg'] = info
        return JsonResponse(result)
    user = UserProfile(
        username=username,
        password=make_password(password1),
        is_admin = True if UserProfile.objects.count()==0 else False,
        is_superuser = True if UserProfile.objects.count()==0 else False,
        is_active = True
    )
    user.save()
    result['msg'] = info
    result['code'] = 1
    return JsonResponse(result)

@login_required(login_url='/api/user_action?action=login')
def user_logout(request):
    info = ''
    auth.logout(request)
    return HttpResponseRedirect('/api/user_action?action=login')
        
def get_single_info(uid):
    online_count = 0
    peers = RustDeskPeer.objects.filter(Q(uid=uid))
    rids = [x.rid for x in peers]
    peers = {x.rid:model_to_dict(x) for x in peers}
    #print(peers)
    devices = RustDesDevice.objects.filter(rid__in=rids)
    devices = {x.rid:x for x in devices}

    for rid in peers.keys():
        peers[rid]['has_rhash'] = _('yes') if len(peers[rid]['rhash'])>1 else _('no')
        peers[rid]['status'] = _('X')

    now = timezone.now()
    for rid, device in devices.items():
        peers[rid]['create_time'] = device.create_time.strftime('%Y-%m-%d')
        peers[rid]['update_time'] = device.update_time.strftime('%Y-%m-%d %H:%M')
        peers[rid]['version'] = device.version
        peers[rid]['memory'] = device.memory
        peers[rid]['cpu'] = device.cpu
        peers[rid]['os'] = device.os
        peers[rid]['ip'] = device.ip
        if (now - device.update_time).total_seconds() <= 120:
            peers[rid]['status'] = _('Online')
            online_count += 1
        else:
            peers[rid]['status'] = _('X')

    sorted_peers = sorted(peers.items(), key=custom_sort, reverse=True)
    new_ordered_dict = {}
    for key, peer in sorted_peers:
        new_ordered_dict[key] = peer

    #return ([v for k,v in peers.items()], online_count)
    return ([v for k,v in new_ordered_dict.items()], online_count)

def get_all_info():
    online_count = 0
    devices = RustDesDevice.objects.all()
    peers = RustDeskPeer.objects.all()
    devices = {x.rid:model_to_dict2(x) for x in devices}
    now = datetime.datetime.now()
    for peer in peers:
        user = UserProfile.objects.filter(Q(id=peer.uid)).first()
        device = devices.get(peer.rid, None)
        if device:
            devices[peer.rid]['rust_user'] = user.username
    
    for k, v in devices.items():
        if (now-datetime.datetime.strptime(v['update_time'], '%Y-%m-%d %H:%M')).seconds <=120:
            devices[k]['status'] = _('Online')
            online_count += 1
        else: 
           devices[k]['status'] = _('X')

    sorted_devices = sorted(devices.items(), key=custom_sort, reverse=True)
    new_ordered_dict = {}
    for key, device in sorted_devices:
        new_ordered_dict[key] = device
    return ([v for k,v in new_ordered_dict.items()], online_count)

def custom_sort(item):
    status = item[1]['status']
    if status == 'Online':
        return 1
    else:
        return 0
    
def get_conn_log():
    logs = ConnLog.objects.all()
    logs = {x.id:model_to_dict(x) for x in logs}
    
    for k, v in logs.items():
        try:
            peer = RustDeskPeer.objects.get(rid=v['rid'])
            logs[k]['alias'] = peer.alias
        except:
            logs[k]['alias'] = 'UNKNOWN'
        try:
            peer = RustDeskPeer.objects.get(rid=v['from_id'])
            logs[k]['from_alias'] = peer.alias
        except:
            logs[k]['from_alias'] = 'UNKNOWN'
        #from_zone = tz.tzutc()
        #to_zone = tz.tzlocal()
        #utc = logs[k]['logged_at']
        #utc = utc.replace(tzinfo=from_zone)
        #logs[k]['logged_at'] = utc.astimezone(to_zone)
        try:
            duration = round((logs[k]['conn_end'] - logs[k]['conn_start']).total_seconds())
            m, s = divmod(duration, 60)
            h, m = divmod(m, 60)
            #d, h = divmod(h, 24)
            logs[k]['duration'] = f'{h:02d}:{m:02d}:{s:02d}'
        except:
            logs[k]['duration'] = -1

    sorted_logs = sorted(logs.items(), key=lambda x: x[1]['conn_start'], reverse=True)
    new_ordered_dict = {}
    for key, alog in sorted_logs:
        new_ordered_dict[key] = alog

    return [v for k, v in new_ordered_dict.items()]

def get_file_log():
    logs = FileLog.objects.all()
    logs = {x.id:model_to_dict(x) for x in logs}

    for k, v in logs.items():
        try:
            peer_remote = RustDeskPeer.objects.get(rid=v['remote_id'])
            logs[k]['remote_alias'] = peer_remote.alias
        except:
            logs[k]['remote_alias'] = 'UNKNOWN'
        try:
            peer_user = RustDeskPeer.objects.get(rid=v['user_id'])
            logs[k]['user_alias'] = peer_user.alias
        except:
            logs[k]['user_alias'] = 'UNKNOWN'

    sorted_logs = sorted(logs.items(), key=lambda x: x[1]['logged_at'], reverse=True)
    new_ordered_dict = {}
    for key, alog in sorted_logs:
        new_ordered_dict[key] = alog

    return [v for k, v in new_ordered_dict.items()]

@login_required(login_url='/api/user_action?action=login')
def sys_info(request):
    hostname = platform.node()
    cpu_usage = psutil.cpu_percent()
    memory_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent
    print(cpu_usage, memory_usage, disk_usage)
    return render(request, 'show_sys_info.html', {'hostname':hostname, 'cpu_usage':cpu_usage, 'memory_usage':memory_usage, 'disk_usage':disk_usage, 'phone_or_desktop': is_mobile(request)})

@login_required(login_url='/api/user_action?action=login')
def clients(request):
    basedir = os.path.join('clients')
    # androidaarch64 = os.path.join(basedir,'android','aarch64')
    # androidarmv7 = os.path.join(basedir,'android','armv7')
    # linuxaarch64 = os.path.join(basedir,'linux','aarch64')
    # linuxx86_64 = os.path.join(basedir,'linux','x86_64')
    # mocos = os.path.join(basedir,'macOS')
    # sciter = os.path.join(basedir,'sciter')
    custom = os.path.join(basedir,'custom')
    # client_files = {}
    client_custom_files = {}
    # if os.path.exists(basedir):
    #     for file in os.listdir(basedir):
    #         if (file.endswith(".exe") or file.endswith(".msi")):
    #             filepath = os.path.join(basedir,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': basedir
    #             }
    # if os.path.exists(androidaarch64):
    #     for file in os.listdir(androidaarch64):
    #         if file.endswith(".apk"):
    #             filepath = os.path.join(androidaarch64,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': androidaarch64
    #             }
    # if os.path.exists(androidarmv7):
    #     for file in os.listdir(androidarmv7):
    #         if file.endswith(".apk"):
    #             filepath = os.path.join(androidarmv7,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': androidarmv7
    #             }
    # if os.path.exists(linuxaarch64):
    #     for file in os.listdir(linuxaarch64):
    #         if (file.endswith(".rpm") or file.endswith(".deb")):
    #             filepath = os.path.join(linuxaarch64,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': linuxaarch64
    #             }
    # if os.path.exists(linuxx86_64):
    #     for file in os.listdir(linuxx86_64):
    #         if (file.endswith(".rpm") or file.endswith(".deb")):
    #             filepath = os.path.join(linuxx86_64,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': linuxx86_64
    #             }
    # if os.path.exists(mocos):
    #     for file in os.listdir(mocos):
    #         if file.endswith(".dmg"):
    #             filepath = os.path.join(mocos,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': mocos
    #             }
    # if os.path.exists(sciter):
    #     for file in os.listdir(sciter):
    #         if file.endswith(".exe"):
    #             filepath = os.path.join(sciter,file)
    #             modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
    #             client_files[file] = {
    #                 'file': file,
    #                 'modified': modified,
    #                 'path': sciter
    #             }
    if os.path.exists(custom):
        for file in os.listdir(custom):
            #if file.endswith(".exe"):
            filepath = os.path.join(custom,file)
            modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %I:%M:%S %p')
            client_custom_files[file] = {
                'file': file,
                'modified': modified,
                'path': custom
            }
    pending_clients = GithubRun.objects.exclude(status__in=["Success", "Generation failed, try again", "Generation cancelled, try again"])
    # return render(request, 'clients.html', {'client_files': client_files, 'client_custom_files': client_custom_files, 'phone_or_desktop': is_mobile(request)})
    return render(request, 'clients.html', {'pending_clients': pending_clients, 'client_custom_files': client_custom_files, 'phone_or_desktop': is_mobile(request)})

def download_file(request, filename, path):
    file_path = os.path.join(str(BASE_DIR),path,filename)
    with open(file_path, 'rb') as file:
        response = HttpResponse(file, headers={
            'Content-Type': 'application/x-binary',
            'Content-Disposition': f'attachment; filename="{filename}"'
        })
    return response

@login_required(login_url='/api/user_action?action=login')
def download(request):
    filename = request.GET['filename']
    path = request.GET['path']
    return download_file(request, filename, path)

@login_required(login_url='/api/user_cation?action=login')
def delete_file(request):
    filename = request.GET['filename']
    path = request.GET['path']
    file_path = os.path.join(str(BASE_DIR),path,filename)
    if os.path.isfile(file_path):
        os.remove(file_path)
    return HttpResponseRedirect('/api/clients')

@login_required(login_url='/api/user_action?action=login')
def add_peer(request):
    if request.method == 'POST':
        form = AddPeerForm(request.POST)
        if form.is_valid():
            rid = form.cleaned_data['clientID']
            uid = request.user.id
            username = form.cleaned_data['username']
            hostname = form.cleaned_data['hostname']
            plat = form.cleaned_data['platform']
            alias = form.cleaned_data['alias']
            tags = form.cleaned_data['tags']
            ip = form.cleaned_data['ip']

            peer = RustDeskPeer(
                uid = uid,
                rid = rid,
                username = username,
                hostname = hostname,
                platform = plat,
                alias = alias,
                tags = tags,
                ip = ip
            )
            peer.save()
            return HttpResponseRedirect('/api/work')
    else:
        rid = request.GET.get('rid','')
        form = AddPeerForm()
    return render(request, 'add_peer.html', {'form': form, 'rid': rid, 'phone_or_desktop': is_mobile(request)})

@login_required(login_url='/api/user_action?action=login')
def edit_peer(request):
    if request.method == 'POST':
        form = EditPeerForm(request.POST)
        if form.is_valid():
            rid = form.cleaned_data['clientID']
            uid = request.user.id
            username = form.cleaned_data['username']
            hostname = form.cleaned_data['hostname']
            plat = form.cleaned_data['platform']
            alias = form.cleaned_data['alias']
            tags = form.cleaned_data['tags']

            updated_peer = RustDeskPeer.objects.get(rid=rid,uid=uid)
            updated_peer.username=username
            updated_peer.hostname=hostname
            updated_peer.platform=plat
            updated_peer.alias=alias
            updated_peer.tags=tags
            updated_peer.save()

            return HttpResponseRedirect('/api/work')
        else:
            print(form.errors)
    else:
        rid = request.GET.get('rid','')
        peer = RustDeskPeer.objects.get(rid=rid)
        initial_data = {
            'clientID': rid,
            'alias': peer.alias,
            'tags': peer.tags,
            'username': peer.username,
            'hostname': peer.hostname,
            'platform': peer.platform,
            'ip': peer.ip
        }
        form = EditPeerForm(initial=initial_data)
        return render(request, 'edit_peer.html', {'form': form, 'peer': peer, 'phone_or_desktop': is_mobile(request)})
    
@login_required(login_url='/api/user_action?action=login')
def assign_peer(request):
    if request.method == 'POST':
        form = AssignPeerForm(request.POST)
        if form.is_valid():
            rid = form.cleaned_data['clientID']
            uid = form.cleaned_data['uid']
            username = form.cleaned_data['username']
            hostname = form.cleaned_data['hostname']
            plat = form.cleaned_data['platform']
            alias = form.cleaned_data['alias']
            tags = form.cleaned_data['tags']
            ip = form.cleaned_data['ip']

            peer = RustDeskPeer(
                uid = uid.id,
                rid = rid,
                username = username,
                hostname = hostname,
                platform = plat,
                alias = alias,
                tags = tags,
                ip = ip
            )
            peer.save()
            return HttpResponseRedirect('/api/work')
        else:
            print(form.errors)
    else:
        rid = request.GET.get('rid')
        form = AssignPeerForm()
        #get list of users from the database
        return render(request, 'assign_peer.html', {'form':form, 'rid': rid, 'phone_or_desktop': is_mobile(request)})
    
@login_required(login_url='/api/user_action?action=login')
def delete_peer(request):
    rid = request.GET.get('rid')
    peer = RustDeskPeer.objects.filter(Q(uid=request.user.id) & Q(rid=rid))
    peer.delete()
    return HttpResponseRedirect('/api/work')

@login_required(login_url='/api/user_action?action=login')
def conn_log(request):
    paginator = Paginator(get_conn_log(), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'show_conn_log.html', {'page_obj':page_obj, 'phone_or_desktop': is_mobile(request)})

@login_required(login_url='/api/user_action?action=login')
def file_log(request):
    paginator = Paginator(get_file_log(), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'show_file_log.html', {'page_obj':page_obj, 'phone_or_desktop': is_mobile(request)})

@login_required(login_url='/api/user_action?action=login')
def work(request):
    username = request.user
    u = UserProfile.objects.get(username=username)
    
    show_type = request.GET.get('show_type', '')
    show_all = True if show_type == 'admin' and u.is_admin else False
    all_info, online_count_all = get_all_info()
    single_info, online_count_single = get_single_info(u.id)
    paginator = Paginator(all_info, 100) if show_type == 'admin' and u.is_admin else Paginator(single_info, 100)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'show_work.html', {'u':u, 'show_all':show_all, 'page_obj':page_obj, 'online_count_single':online_count_single, 'online_count_all':online_count_all, 'phone_or_desktop': is_mobile(request)})

@login_required(login_url='/api/user_action?action=login')
def down_peers(request):
    username = request.user
    u = UserProfile.objects.get(username=username)

    if not u.is_admin:
        print(u.is_admin)
        return HttpResponseRedirect('/api/work')
    
    all_info = get_all_info()
    f = xlwt.Workbook(encoding='utf-8')
    sheet1 = f.add_sheet(_(u'设备信息表'), cell_overwrite_ok=True)
    all_fields = [x.name for x in RustDesDevice._meta.get_fields()]
    all_fields.append('rust_user')
    for i, one in enumerate(all_info):
        for j, name in enumerate(all_fields):
            if i == 0:
                # 写入列名
                sheet1.write(i, j, name)
            sheet1.write(i+1, j, one.get(name, '-'))

    sio = BytesIO()
    f.save(sio)
    sio.seek(0)
    response = HttpResponse(sio.getvalue(), content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename=DeviceInfo.xls'
    response.write(sio.getvalue())
    return response
    
def check_sharelink_expired(sharelink):
    now = datetime.datetime.now()
    if sharelink.create_time > now:
        return False
    if (now - sharelink.create_time).seconds <15 * 60:
        return False
    else:
        sharelink.is_expired = True
        sharelink.save()
        return True


@login_required(login_url='/api/user_action?action=login')
def share(request):
    peers = RustDeskPeer.objects.filter(Q(uid=request.user.id))
    sharelinks = ShareLink.objects.filter(Q(uid=request.user.id) & Q(is_used=False) & Q(is_expired=False))


    # 省资源：处理已过期请求，不主动定时任务轮询请求，在任意地方请求时，检查是否过期，过期则保存。
    now = datetime.datetime.now()
    for sl in sharelinks:
        check_sharelink_expired(sl)
    sharelinks = ShareLink.objects.filter(Q(uid=request.user.id) & Q(is_used=False) & Q(is_expired=False))
    peers = [{'id':ix+1, 'name':f'{p.rid}|{p.alias}'} for ix, p in enumerate(peers)]
    sharelinks = [{'shash':s.shash, 'is_used':s.is_used, 'is_expired':s.is_expired, 'create_time':s.create_time, 'peers':s.peers} for ix, s in enumerate(sharelinks)]

    if request.method == 'GET':
        url = request.build_absolute_uri()
        if url.endswith('share'):
            return render(request, 'share.html', {'peers':peers, 'sharelinks':sharelinks})
        else:
            shash = url.split('/')[-1]
            sharelink = ShareLink.objects.filter(Q(shash=shash))
            msg = ''
            title = 'success'
            if not sharelink:
                title = 'mistake'
                msg = f'Link{url}:<br>Share the link does not exist or have failed.'
            else:
                sharelink = sharelink[0]
                if str(request.user.id) == str(sharelink.uid):
                    title = 'mistake'
                    msg = f'Link{url}:<br><br>Lets say, you cant share the link to yourself, right?Intersection'
                else:
                    sharelink.is_used = True
                    sharelink.save()
                    peers = sharelink.peers
                    peers = peers.split(',')
                    # 自己的peers若重叠，需要跳过
                    peers_self_ids = [x.rid for x in RustDeskPeer.objects.filter(Q(uid=request.user.id))]
                    peers_share = RustDeskPeer.objects.filter(Q(rid__in=peers) & Q(uid=sharelink.uid))
                    peers_share_ids = [x.rid for x in peers_share]

                    for peer in peers_share:
                        if peer.rid in peers_self_ids:
                            continue
                        #peer = RustDeskPeer.objects.get(rid=peer.rid)
                        peer_f = RustDeskPeer.objects.filter(Q(rid=peer.rid) & Q(uid=sharelink.uid))
                        if not peer_f:
                            msg += f"{peer.rid}existed,"
                            continue
                        
                        if len(peer_f) > 1:
                             msg += f'{peer.rid}There are multiple,Has skipped. '
                             continue
                        peer = peer_f[0]
                        peer.id = None
                        peer.uid = request.user.id
                        peer.save()
                        msg += f"{peer.rid},"

                    msg += 'Has been successfully obtained.'

            title = _(title)
            msg = _(msg)
            return render(request, 'msg.html', {'title':msg, 'msg':msg})
    else:
        data = request.POST.get('data', '[]')

        data = json.loads(data)
        if not data:
            return JsonResponse({'code':0, 'msg':_('数据为空。')})
        rustdesk_ids = [x['title'].split('|')[0] for x in data]
        rustdesk_ids = ','.join(rustdesk_ids)
        sharelink = ShareLink(
            uid=request.user.id,
            shash = getStrMd5(str(time.time())+salt),
            peers=rustdesk_ids,
        )
        sharelink.save()

        return JsonResponse({'code':1, 'shash':sharelink.shash})

def is_mobile(request):
    user_agent = request.META['HTTP_USER_AGENT']
    if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
        return 'base_phone.html'
    else:
        return 'base.html'
