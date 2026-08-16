# -*- coding: utf-8 -*-
"""七牛云上传/下载模块：照片与台账的上传、下载。"""
import os
import ssl
import urllib.parse
import urllib.request


def upload_to_qiniu(local_path, key, access_key, secret_key, bucket, domain):
    """
    上传单个本地文件到七牛云。
    :return: 可访问 URL；失败返回 None。
    """
    try:
        from qiniu import Auth, put_file
        q = Auth(access_key.strip(), secret_key.strip())
        token = q.upload_token(bucket.strip(), key)
        ret, info = put_file(token, key, local_path)
        if info.status_code == 200:
            dom = domain.strip().rstrip('/')
            if dom and not dom.startswith(("http://", "https://")):
                dom = "https://" + dom
            return f"{dom}/{key}"
    except Exception:
        return None
    return None


def upload_list_to_qiniu(local_paths, prefix, access_key, secret_key, bucket, domain):
    """
    上传多个本地文件到七牛云，prefix 为 key 前缀（如 订单主号/送货单照片）。
    :return: 成功上传的 URL 列表。
    """
    if not (access_key and secret_key and bucket and domain):
        return []
    urls = []
    for lp in (local_paths or []):
        key = f"{prefix.rstrip('/')}/{os.path.basename(lp)}"
        url = upload_to_qiniu(lp, key, access_key, secret_key, bucket, domain)
        if url:
            urls.append(url)
    return urls


def delete_from_qiniu(key, access_key, secret_key, bucket):
    """删除七牛云上的单个文件。成功返回 True。"""
    try:
        from qiniu import Auth, BucketManager
        q = Auth(access_key.strip(), secret_key.strip())
        bm = BucketManager(q)
        _ret, info = bm.delete(bucket.strip(), key)
        return info.status_code == 200
    except Exception:
        return False

def delete_list_from_qiniu(keys, access_key, secret_key, bucket):
    """批量删除七牛云文件。返回成功删除的数量。"""
    n = 0
    for k in (keys or []):
        if delete_from_qiniu(k, access_key, secret_key, bucket):
            n += 1
    return n

def download_from_qiniu(key, local_path, access_key, secret_key, domain):
    """
    从七牛云下载文件到本地。支持公开/私有空间（自动签名）。
    使用不校验 SSL 证书的上下文（兼容七牛云旧证书）。
    :return: 成功返回 True，失败返回 False。
    """
    try:
        from qiniu import Auth
        dom = domain.strip().rstrip('/')
        if dom and not dom.startswith(("http://", "https://")):
            dom = "https://" + dom
        q = Auth(access_key.strip(), secret_key.strip())
        quoted = urllib.parse.quote(key, safe="/")
        url = f"{dom}/{quoted}"
        private_url = q.private_download_url(url, expires=3600)
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(private_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def list_files(prefix, access_key, secret_key, bucket, limit=1000):
    """
    列出七牛云空间指定前缀下的所有文件 key（自动分页拉全）。
    :param prefix: 前缀，如 "photos/"
    :return: key 列表；失败返回空列表。
    """
    try:
        from qiniu import Auth, BucketManager
        q = Auth(access_key.strip(), secret_key.strip())
        bm = BucketManager(q)
        keys = []
        marker = None
        while True:
            ret, _eof, info = bm.list(bucket.strip(), prefix=prefix, marker=marker, limit=limit)
            if info.status_code != 200:
                break
            for item in (ret.get("items") or []):
                k = item.get("key")
                if k:
                    keys.append(k)
            marker = ret.get("marker")
            if not marker:
                break
        return keys
    except Exception:
        return []
