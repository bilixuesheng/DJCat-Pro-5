/*
 * DJCat Pro 5 Client Update installer.
 *
 * Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>
 *
 *   pid         - PID of the DJCat process to wait for
 *   app_dir     - installation directory to replace
 *   exe_path    - full path to djcat.exe, relaunched once the update lands
 *   staging_dir - directory holding the already extracted new version
 *
 * The install is a directory swap, not a per-file copy: the staged tree is
 * renamed next to app_dir, app_dir is renamed aside as a backup, and the staged
 * tree takes its place. Every step is a same-volume rename, so there is never a
 * half-updated directory and any failure puts the backup back. A per-file copy
 * has no such property: one failed file leaves the install in a state nothing
 * can recover, and the file that fails may be the updater's own image.
 *
 * The swap-with-rollback and relocate-out-of-the-target ideas come from
 * Ghost-Downloader-3's updater (GPL-3.0), like this project's download worker.
 * Two things are deliberately NOT copied from it:
 *
 *   - Ghost copies its portable folder into the new tree. DJCat's Portable Mode
 *     keeps the App Data Directory at app_dir\DJCatPro, which holds installed
 *     Applications and the Application Store cache and is routinely gigabytes,
 *     so it is renamed into the staged tree instead. A rename is instant and,
 *     unlike a copy, cannot half-finish.
 *   - Ghost's macOS/Linux branches are dropped; DJCat is Windows only.
 *
 * Elevation is kept, and so is the de-elevation that must go with it. The
 * installer is PrivilegesRequired=lowest, but the release also ships a ZIP that
 * can be extracted anywhere, including a protected directory. Such an install
 * already falls back to the per-user App Data Directory (see
 * app/config/paths.py), and without elevation its Client Update could never
 * land at all.
 */

#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define PATH_BUF 4096
#define WAIT_TIMEOUT_MS 30000
#define RENAME_RETRIES 10
#define RENAME_RETRY_MS 200

enum {
    EXIT_OK = 0,
    EXIT_BAD_ARGS = 1,
    EXIT_STAGING_INVALID = 2,
    EXIT_NOT_WRITABLE = 3,
    EXIT_SWAP_FAILED = 4,
    EXIT_LAUNCH_FAILED = 5,
};

static FILE *g_log = NULL;
static wchar_t g_logPath[PATH_BUF];

/* Set when a move gave up because another process still has something in the
   tree open: a program running from it, or one whose working directory is inside
   it, which Windows also refuses to rename. Earlier DJCat versions ran with
   app_dir as their working directory and every program they opened inherited
   it, so the reason the user sees says what to close. */
static BOOL g_moveLocked = FALSE;
#define LOCKED_REASON L"安装目录正被其他程序占用，请先关闭从电教猫打开的程序"

/* _snwprintf does not terminate on truncation; every path goes through here. */
static void formatPath(wchar_t *out, size_t size, const wchar_t *format, ...) {
    va_list ap;
    va_start(ap, format);
    _vsnwprintf(out, size, format, ap);
    va_end(ap);
    out[size - 1] = L'\0';
}

static void logMsg(const wchar_t *format, ...) {
    if (!g_log) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fwprintf(g_log, L"[%04d-%02d-%02d %02d:%02d:%02d] ",
             st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    va_list ap;
    va_start(ap, format);
    vfwprintf(g_log, format, ap);
    va_end(ap);
    fwprintf(g_log, L"\n");
    fflush(g_log);
}

static void openLog(const wchar_t *directory) {
    formatPath(g_logPath, PATH_BUF, L"%ls\\updater.log", directory);
    g_log = _wfopen(g_logPath, L"a");
}

static void closeLog(void) {
    if (g_log) {
        fclose(g_log);
        g_log = NULL;
    }
}

static BOOL hasDir(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES &&
           (attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL hasFile(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES &&
           !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void directoryOf(wchar_t *path) {
    wchar_t *slash = wcsrchr(path, L'\\');
    wchar_t *forward = wcsrchr(path, L'/');
    if (forward > slash) slash = forward;
    if (slash) *slash = L'\0';
}

/* Callers may hand us forward slashes; Win32 accepts them but a prefix compare
   against GetModuleFileNameW's backslashes would not match, which would silently
   skip the relocation this design depends on. */
static void normalizeSeparators(wchar_t *path) {
    for (wchar_t *cursor = path; *cursor; cursor++)
        if (*cursor == L'/') *cursor = L'\\';
}

static void stripTrailingSlashes(wchar_t *path) {
    size_t length = wcslen(path);
    while (length > 1 && (path[length - 1] == L'\\' || path[length - 1] == L'/'))
        path[--length] = L'\0';
}

static const wchar_t *baseNameOf(const wchar_t *path) {
    const wchar_t *slash = wcsrchr(path, L'\\');
    const wchar_t *forward = wcsrchr(path, L'/');
    if (forward > slash) slash = forward;
    return slash ? slash + 1 : path;
}

static BOOL deleteTree(const wchar_t *directory);

static void deleteTreeContents(const wchar_t *directory) {
    wchar_t pattern[PATH_BUF];
    formatPath(pattern, PATH_BUF, L"%ls\\*", directory);
    WIN32_FIND_DATAW found;
    HANDLE search = FindFirstFileW(pattern, &found);
    if (search == INVALID_HANDLE_VALUE) return;
    do {
        if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0)
            continue;
        wchar_t path[PATH_BUF];
        formatPath(path, PATH_BUF, L"%ls\\%ls", directory, found.cFileName);
        if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            deleteTree(path);
        } else {
            SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
            DeleteFileW(path);
        }
    } while (FindNextFileW(search, &found));
    FindClose(search);
}

static BOOL deleteTree(const wchar_t *directory) {
    if (!hasDir(directory)) return TRUE;
    deleteTreeContents(directory);
    return RemoveDirectoryW(directory);
}

/* Anti-virus and indexers hold brief handles on a tree that was just written. */
static BOOL moveTree(const wchar_t *from, const wchar_t *to) {
    for (int attempt = 0; attempt < RENAME_RETRIES; attempt++) {
        if (MoveFileW(from, to)) return TRUE;
        DWORD error = GetLastError();
        if (error != ERROR_ACCESS_DENIED && error != ERROR_SHARING_VIOLATION) {
            logMsg(L"move \"%ls\" -> \"%ls\" failed (err %lu)", from, to, error);
            return FALSE;
        }
        Sleep(RENAME_RETRY_MS);
    }
    logMsg(L"move \"%ls\" -> \"%ls\" still locked after %d tries",
           from, to, RENAME_RETRIES);
    g_moveLocked = TRUE;
    return FALSE;
}

static BOOL canWriteDir(const wchar_t *directory) {
    wchar_t probe[PATH_BUF];
    formatPath(probe, PATH_BUF, L"%ls\\.djcat-update-probe", directory);
    HANDLE handle = CreateFileW(
        probe, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (handle == INVALID_HANDLE_VALUE) return FALSE;
    CloseHandle(handle);
    return TRUE;
}

static BOOL isElevated(void) {
    HANDLE token = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return FALSE;
    TOKEN_ELEVATION elevation = {0};
    DWORD size = 0;
    BOOL elevated = GetTokenInformation(token, TokenElevation, &elevation,
                                        sizeof(elevation), &size) &&
                    elevation.TokenIsElevated;
    CloseHandle(token);
    return elevated;
}

/* Re-launch through UAC with the same arguments. FALSE means the prompt was
   declined or could not be shown, which is a reason to report, not to retry. */
static BOOL restartElevated(int argc, wchar_t **argv) {
    wchar_t selfPath[PATH_BUF];
    if (!GetModuleFileNameW(NULL, selfPath, PATH_BUF)) return FALSE;
    selfPath[PATH_BUF - 1] = L'\0';

    wchar_t parameters[PATH_BUF * 2];
    parameters[0] = L'\0';
    for (int index = 1; index < argc; index++) {
        wchar_t argument[PATH_BUF];
        formatPath(argument, PATH_BUF,
                   index == 1 ? L"\"%ls\"" : L" \"%ls\"", argv[index]);
        wcsncat(parameters, argument, PATH_BUF * 2 - wcslen(parameters) - 1);
    }

    SHELLEXECUTEINFOW info = {0};
    info.cbSize = sizeof(info);
    info.fMask = SEE_MASK_NOCLOSEPROCESS;
    info.lpVerb = L"runas";
    info.lpFile = selfPath;
    info.lpParameters = parameters;
    info.nShow = SW_HIDE;
    if (!ShellExecuteExW(&info)) return FALSE;
    if (info.hProcess) CloseHandle(info.hProcess);
    return TRUE;
}

/*
 * Relaunch DJCat with the logged-in user's token by borrowing Explorer's.
 *
 * This is not optional once the updater can elevate. A CreateProcess from an
 * elevated updater hands DJCat an administrator token, and everything it writes
 * afterwards -- UserConfig.json, the Program directory holding installed
 * Applications, the Application Store cache -- ends up owned by the
 * administrator, so the next ordinary run cannot read its own data. That is a
 * worse and far more confusing failure than the one elevation fixes.
 */
static BOOL startAppAsUser(const wchar_t *exePath, const wchar_t *workingDir,
                           BOOL silent) {
    HWND tray = FindWindowW(L"Shell_TrayWnd", NULL);
    if (!tray) return FALSE;
    DWORD shellPid = 0;
    GetWindowThreadProcessId(tray, &shellPid);
    if (!shellPid) return FALSE;

    HANDLE shell = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, shellPid);
    if (!shell) return FALSE;

    HANDLE shellToken = NULL, userToken = NULL;
    BOOL started = FALSE;
    if (OpenProcessToken(shell, TOKEN_DUPLICATE, &shellToken) &&
        DuplicateTokenEx(shellToken,
                         TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY |
                         TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID,
                         NULL, SecurityImpersonation, TokenPrimary, &userToken)) {
        wchar_t command[PATH_BUF];
        /* 静默轮换时沿用 --silence，否则开机静默启动的会话重启回来会弹窗。*/
        formatPath(command, PATH_BUF, silent ? L"\"%ls\" --silence" : L"\"%ls\"",
                   exePath);
        STARTUPINFOW startup = { .cb = sizeof(startup) };
        PROCESS_INFORMATION process = {0};
        if (CreateProcessAsUserW(userToken, NULL, command, NULL, NULL, FALSE,
                                 0, NULL, workingDir, &startup, &process)) {
            CloseHandle(process.hProcess);
            CloseHandle(process.hThread);
            started = TRUE;
        }
    }
    if (userToken) CloseHandle(userToken);
    if (shellToken) CloseHandle(shellToken);
    CloseHandle(shell);
    return started;
}

static void writeFailureMarker(const wchar_t *appDir, const wchar_t *reason) {
    wchar_t path[PATH_BUF];
    formatPath(path, PATH_BUF, L"%ls\\update-failed.txt", appDir);
    FILE *marker = _wfopen(path, L"w, ccs=UTF-8");
    if (!marker) return;
    fwprintf(marker, L"%ls\n%ls\n", reason, g_logPath);
    fclose(marker);
}

static void waitForProcess(DWORD pid) {
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) {
        logMsg(L"OpenProcess(%lu) failed (err %lu), assuming it already exited",
               pid, GetLastError());
        return;
    }
    logMsg(L"waiting for pid %lu", pid);
    DWORD result = WaitForSingleObject(process, WAIT_TIMEOUT_MS);
    CloseHandle(process);
    logMsg(result == WAIT_OBJECT_0 ? L"process exited"
                                   : L"wait returned %lu, proceeding anyway", result);
}

/* True when `path` is `directory` itself or sits underneath it. */
static BOOL isInside(const wchar_t *path, const wchar_t *directory) {
    wchar_t longPath[PATH_BUF], longDir[PATH_BUF];
    if (!GetLongPathNameW(path, longPath, PATH_BUF))
        formatPath(longPath, PATH_BUF, L"%ls", path);
    if (!GetLongPathNameW(directory, longDir, PATH_BUF))
        formatPath(longDir, PATH_BUF, L"%ls", directory);
    normalizeSeparators(longPath);
    normalizeSeparators(longDir);
    stripTrailingSlashes(longDir);
    size_t length = wcslen(longDir);
    if (_wcsnicmp(longPath, longDir, length) != 0) return FALSE;
    wchar_t next = longPath[length];
    return next == L'\0' || next == L'\\' || next == L'/';
}

/*
 * Re-launch from %TEMP% when running from inside the directory about to be
 * renamed. Windows keeps the running image mapped, and the open log lives in
 * the same tree, so either one would block MoveFileW on app_dir.
 *
 * Returns 1 when a relocated copy took over and this process should exit,
 * 0 when already outside app_dir, and -1 when relocation was needed but failed.
 */
static int relocateOutOfAppDir(const wchar_t *appDir, int argc, wchar_t **argv) {
    wchar_t selfPath[PATH_BUF];
    if (!GetModuleFileNameW(NULL, selfPath, PATH_BUF)) return 0;
    selfPath[PATH_BUF - 1] = L'\0';
    if (!isInside(selfPath, appDir)) return 0;

    wchar_t tempRoot[PATH_BUF], tempDir[PATH_BUF], target[PATH_BUF];
    if (!GetTempPathW(PATH_BUF, tempRoot)) return -1;
    formatPath(tempDir, PATH_BUF, L"%ls%ls", tempRoot, L"djcat_updater");
    CreateDirectoryW(tempDir, NULL);
    formatPath(target, PATH_BUF, L"%ls\\updater.exe", tempDir);

    /* A copy left by an earlier update is still mapped only while it runs. */
    DeleteFileW(target);
    if (!CopyFileW(selfPath, target, FALSE)) return -1;

    wchar_t command[PATH_BUF * 2];
    formatPath(command, PATH_BUF * 2, L"\"%ls\"", target);
    for (int index = 1; index < argc; index++) {
        wchar_t argument[PATH_BUF];
        formatPath(argument, PATH_BUF, L" \"%ls\"", argv[index]);
        wcsncat(command, argument, PATH_BUF * 2 - wcslen(command) - 1);
    }

    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION process = {0};
    /* DJCat starts the updater DETACHED_PROCESS, so there is no console to
       inherit; without CREATE_NO_WINDOW Windows gives this console program a
       fresh, visible console window for the whole update. */
    if (!CreateProcessW(target, command, NULL, NULL, FALSE,
                        CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, NULL, tempDir,
                        &startup, &process))
        return -1;
    CloseHandle(process.hProcess);
    CloseHandle(process.hThread);
    return 1;
}

/*
 * Swap the staged tree into place.
 *
 * Only renames, so the window in which app_dir does not exist is as short as
 * the file system can make it, and every failure has an exact inverse.
 */
static BOOL installStagedTree(const wchar_t *appDir, const wchar_t *stagedDir,
                              const wchar_t *backupDir, BOOL hasPortableData) {
    wchar_t portableInApp[PATH_BUF], portableInStaged[PATH_BUF];
    formatPath(portableInApp, PATH_BUF, L"%ls\\DJCatPro", appDir);
    formatPath(portableInStaged, PATH_BUF, L"%ls\\DJCatPro", stagedDir);

    if (hasPortableData) {
        logMsg(L"carrying the portable App Data Directory into the new tree");
        if (!moveTree(portableInApp, portableInStaged)) return FALSE;
    }

    if (!moveTree(appDir, backupDir)) {
        if (hasPortableData) moveTree(portableInStaged, portableInApp);
        return FALSE;
    }

    if (!moveTree(stagedDir, appDir)) {
        logMsg(L"rolling the backup back into place");
        if (!moveTree(backupDir, appDir))
            logMsg(L"BACKUP COULD NOT BE RESTORED, it is still at \"%ls\"", backupDir);
        else if (hasPortableData)
            moveTree(portableInStaged, portableInApp);
        return FALSE;
    }
    return TRUE;
}

/*
 * 反弹窗拦截：把 djcat.exe 版本资源里的 ProductName 和 FileDescription 改成伪装名。
 *
 * 不做"按字符串等长覆盖字节"——伪装名长度任意。而是读出现有版本资源，用它从头重建
 * 一份 VS_VERSIONINFO，只把这两个字符串换掉，其余（公司名、版本号、翻译、固定信息）
 * 原样保留，再用 BeginUpdateResource/UpdateResource/EndUpdateResource 写回。
 * 改坏了 exe 就起不来，所以先备份、写完校验，不通过就还原。
 */

#define APB_VS_VERSION_INFO_ID 1

typedef struct {
    BYTE *data;
    size_t len;
    size_t cap;
    BOOL failed;
} ByteBuf;

static void bufBytes(ByteBuf *b, const void *src, size_t n) {
    if (b->failed) return;
    if (b->len + n > b->cap) {
        size_t cap = b->cap ? b->cap : 256;
        while (cap < b->len + n) cap *= 2;
        BYTE *grown = (BYTE *)realloc(b->data, cap);
        if (!grown) { b->failed = TRUE; return; }
        b->data = grown;
        b->cap = cap;
    }
    memcpy(b->data + b->len, src, n);
    b->len += n;
}

static void bufU16(ByteBuf *b, WORD value) { bufBytes(b, &value, sizeof(value)); }

static void bufWStr(ByteBuf *b, const wchar_t *text) {
    bufBytes(b, text, (wcslen(text) + 1) * sizeof(wchar_t));
}

/* VS_VERSIONINFO 的每个节点都从 32 位边界开始。*/
static void bufAlign(ByteBuf *b) {
    BYTE zero = 0;
    while (!b->failed && (b->len & 3) != 0) bufBytes(b, &zero, 1);
}

/* 写节点头（wLength 先占位）+ key + 对齐；返回起始偏移供 blockEnd 回填 wLength。*/
static size_t blockBegin(ByteBuf *b, WORD valueLength, WORD type,
                         const wchar_t *key) {
    size_t start = b->len;
    bufU16(b, 0);
    bufU16(b, valueLength);
    bufU16(b, type);
    bufWStr(b, key);
    bufAlign(b);
    return start;
}

/* wLength 只到节点内容结束，不含为对齐下一个兄弟而补的填充。*/
static void blockEnd(ByteBuf *b, size_t start) {
    if (b->failed) return;
    WORD length = (WORD)(b->len - start);
    memcpy(b->data + start, &length, sizeof(length));
}

static const wchar_t *readVersionString(const void *info, WORD lang, WORD cp,
                                        const wchar_t *key) {
    wchar_t path[128];
    formatPath(path, 128, L"\\StringFileInfo\\%04x%04x\\%ls", lang, cp, key);
    void *value = NULL;
    UINT length = 0;
    if (VerQueryValueW((void *)info, path, &value, &length) && length)
        return (const wchar_t *)value;
    return NULL;
}

/* 保留的字符串键；ProductName 和 FileDescription 换成伪装名，其余照抄。*/
static const wchar_t *const VERSION_STRING_KEYS[] = {
    L"CompanyName", L"FileDescription", L"FileVersion", L"InternalName",
    L"LegalCopyright", L"LegalTrademarks", L"OriginalFilename",
    L"ProductName", L"ProductVersion", L"Comments",
};

static BOOL readFileVersionInfo(const wchar_t *exe, void **outInfo, DWORD *outSize) {
    DWORD ignored = 0;
    DWORD size = GetFileVersionInfoSizeW(exe, &ignored);
    if (!size) return FALSE;
    void *info = malloc(size);
    if (!info) return FALSE;
    if (!GetFileVersionInfoW(exe, 0, size, info)) {
        free(info);
        return FALSE;
    }
    *outInfo = info;
    *outSize = size;
    return TRUE;
}

static BOOL buildVersionBlob(const void *info, WORD lang, WORD cp,
                             const wchar_t *newName, BYTE **outBlob,
                             DWORD *outLen) {
    void *fixed = NULL;
    UINT fixedLen = 0;
    if (!VerQueryValueW((void *)info, L"\\", &fixed, &fixedLen) || !fixedLen)
        return FALSE;

    ByteBuf b = {0};
    size_t root = blockBegin(&b, (WORD)fixedLen, 0, L"VS_VERSION_INFO");
    bufBytes(&b, fixed, fixedLen);
    bufAlign(&b);

    size_t stringInfo = blockBegin(&b, 0, 1, L"StringFileInfo");
    wchar_t tableKey[9];
    formatPath(tableKey, 9, L"%04x%04x", lang, cp);
    size_t table = blockBegin(&b, 0, 1, tableKey);
    for (size_t i = 0; i < sizeof(VERSION_STRING_KEYS) / sizeof(*VERSION_STRING_KEYS);
         i++) {
        const wchar_t *key = VERSION_STRING_KEYS[i];
        const wchar_t *value =
            (wcscmp(key, L"ProductName") == 0 || wcscmp(key, L"FileDescription") == 0)
                ? newName
                : readVersionString(info, lang, cp, key);
        if (!value) continue;
        bufAlign(&b);
        WORD chars = (WORD)(wcslen(value) + 1);  /* String 的 wValueLength 以字符计 */
        size_t node = blockBegin(&b, chars, 1, key);
        bufWStr(&b, value);
        blockEnd(&b, node);
    }
    blockEnd(&b, table);
    blockEnd(&b, stringInfo);

    bufAlign(&b);
    size_t varInfo = blockBegin(&b, 0, 1, L"VarFileInfo");
    size_t translation = blockBegin(&b, 4, 0, L"Translation");
    WORD pair[2] = {lang, cp};
    bufBytes(&b, pair, sizeof(pair));
    blockEnd(&b, translation);
    blockEnd(&b, varInfo);

    blockEnd(&b, root);

    if (b.failed) {
        free(b.data);
        return FALSE;
    }
    *outBlob = b.data;
    *outLen = (DWORD)b.len;
    return TRUE;
}

static BOOL readProductName(const wchar_t *exe, wchar_t *out, size_t outCount) {
    void *info = NULL;
    DWORD size = 0;
    if (!readFileVersionInfo(exe, &info, &size)) return FALSE;
    void *translation = NULL;
    UINT length = 0;
    BOOL ok = FALSE;
    if (VerQueryValueW(info, L"\\VarFileInfo\\Translation", &translation, &length) &&
        length >= 4) {
        WORD *pair = (WORD *)translation;
        const wchar_t *value = readVersionString(info, pair[0], pair[1], L"ProductName");
        if (value) {
            wcsncpy(out, value, outCount - 1);
            out[outCount - 1] = L'\0';
            ok = TRUE;
        }
    }
    free(info);
    return ok;
}

/* RT_VERSION 资源在 PE 里的语言，未必等于翻译里的 langID；用它更新才替换而不是新增一条。*/
static WORD g_versionResourceLang;
static BOOL g_versionResourceLangFound;

static BOOL CALLBACK enumVersionLangProc(HMODULE module, LPCWSTR type, LPCWSTR name,
                                         WORD lang, LONG_PTR param) {
    (void)module;
    (void)type;
    (void)name;
    (void)param;
    g_versionResourceLang = lang;
    g_versionResourceLangFound = TRUE;
    return FALSE;  /* 第一个就够 */
}

static BOOL versionResourceLang(const wchar_t *exe, WORD *outLang) {
    HMODULE module = LoadLibraryExW(exe, NULL, LOAD_LIBRARY_AS_DATAFILE);
    if (!module) return FALSE;
    g_versionResourceLangFound = FALSE;
    g_versionResourceLang = 0;
    EnumResourceLanguagesW(module, RT_VERSION,
                           MAKEINTRESOURCEW(APB_VS_VERSION_INFO_ID),
                           enumVersionLangProc, 0);
    FreeLibrary(module);
    if (!g_versionResourceLangFound) return FALSE;
    *outLang = g_versionResourceLang;
    return TRUE;
}

static BOOL stampProductName(const wchar_t *exe, const wchar_t *newName) {
    void *info = NULL;
    DWORD size = 0;
    if (!readFileVersionInfo(exe, &info, &size)) {
        logMsg(L"读不到现有版本资源，放弃改名");
        return FALSE;
    }
    void *translation = NULL;
    UINT translationLen = 0;
    if (!VerQueryValueW(info, L"\\VarFileInfo\\Translation", &translation,
                        &translationLen) || translationLen < 4) {
        logMsg(L"读不到翻译信息，放弃改名");
        free(info);
        return FALSE;
    }
    WORD lang = ((WORD *)translation)[0];
    WORD codepage = ((WORD *)translation)[1];
    BYTE *blob = NULL;
    DWORD blobLen = 0;
    BOOL built = buildVersionBlob(info, lang, codepage, newName, &blob, &blobLen);
    free(info);
    if (!built) {
        logMsg(L"重建版本资源失败");
        return FALSE;
    }

    WORD resourceLang = lang;
    if (!versionResourceLang(exe, &resourceLang)) {
        /* 读不到 RT_VERSION 的真实资源语言时退回翻译里的语言；两者不一致会让
           UpdateResource 新增一条而不是替换，伪装就白改了——极少见，记一行好排查。*/
        resourceLang = lang;
        logMsg(L"读不到 RT_VERSION 资源语言，回退用翻译语言 0x%04x", lang);
    }

    wchar_t backup[PATH_BUF];
    formatPath(backup, PATH_BUF, L"%ls.apb-backup", exe);
    DeleteFileW(backup);
    if (!CopyFileW(exe, backup, FALSE)) {
        logMsg(L"无法备份 \"%ls\"，放弃改名 (err %lu)", exe, GetLastError());
        free(blob);
        return FALSE;
    }

    BOOL ok = FALSE;
    HANDLE update = BeginUpdateResourceW(exe, FALSE);
    if (update) {
        BOOL wrote = UpdateResourceW(update, RT_VERSION,
                                     MAKEINTRESOURCEW(APB_VS_VERSION_INFO_ID),
                                     resourceLang, blob, blobLen);
        if (!EndUpdateResourceW(update, !wrote)) wrote = FALSE;
        if (wrote) {
            wchar_t check[256];
            ok = readProductName(exe, check, 256) && wcscmp(check, newName) == 0;
            if (!ok) logMsg(L"改名后校验不通过");
        } else {
            logMsg(L"写入版本资源失败 (err %lu)", GetLastError());
        }
    } else {
        logMsg(L"BeginUpdateResource 失败 (err %lu)", GetLastError());
    }
    free(blob);

    if (ok) {
        DeleteFileW(backup);
    } else if (CopyFileW(backup, exe, FALSE)) {
        DeleteFileW(backup);
        logMsg(L"已从备份还原 exe");
    } else {
        logMsg(L"还原失败，备份留在 \"%ls\"", backup);
    }
    return ok;
}

/*
 * 用登录用户的身份重启 DJCat（提权时经 Explorer 令牌降权），返回是否起来了。
 * silent 为真时带上 --silence：开机静默启动的会话若因自动轮换换名而重启，
 * 必须仍然静默，否则主窗口会在教室投影上凭空弹出。
 */
static BOOL relaunchApp(const wchar_t *exePath, const wchar_t *workingDir,
                        BOOL silent) {
    logMsg(L"launching \"%ls\"%ls", exePath, silent ? L" --silence" : L"");
    if (isElevated() && startAppAsUser(exePath, workingDir, silent)) {
        logMsg(L"relaunched DJCat with the logged-in user's token");
        return TRUE;
    }
    wchar_t command[PATH_BUF];
    formatPath(command, PATH_BUF, silent ? L"\"%ls\" --silence" : L"\"%ls\"",
               exePath);
    STARTUPINFOW startup = {.cb = sizeof(startup)};
    PROCESS_INFORMATION process = {0};
    if (CreateProcessW(exePath, command, NULL, NULL, FALSE, 0, NULL, workingDir,
                       &startup, &process)) {
        CloseHandle(process.hProcess);
        CloseHandle(process.hThread);
        return TRUE;
    }
    logMsg(L"CreateProcess failed (err %lu), falling back to ShellExecute",
           GetLastError());
    if ((INT_PTR)ShellExecuteW(NULL, L"open", exePath,
                               silent ? L"--silence" : NULL, workingDir,
                               SW_SHOWNORMAL) <= 32) {
        logMsg(L"could not relaunch DJCat");
        return FALSE;
    }
    return TRUE;
}

/*
 * 反弹窗拦截模式：等 DJCat 退出 → 改 exe 的产品名 → 降权重启。
 * 只改一个文件、不动目录，所以不必像更新那样把自己挪出 app_dir。
 * Usage: updater.exe --stamp-product-name <pid> <exe_path> <product_name> [silent]
 *   silent 为 "1" 时重启带 --silence（开机静默启动的会话自动轮换换名用）。
 */
static int stampMode(int argc, wchar_t **argv) {
    if (argc < 5) {
        fwprintf(stderr,
                 L"Usage: updater.exe --stamp-product-name <pid> <exe> <name> [silent]\n");
        return EXIT_BAD_ARGS;
    }
    DWORD pid = (DWORD)_wtoi(argv[2]);
    BOOL silent = (argc > 5 && argv[5][0] == L'1');
    wchar_t exe[PATH_BUF], name[PATH_BUF], dir[PATH_BUF];
    formatPath(exe, PATH_BUF, L"%ls", argv[3]);
    formatPath(name, PATH_BUF, L"%ls", argv[4]);
    normalizeSeparators(exe);
    formatPath(dir, PATH_BUF, L"%ls", exe);
    directoryOf(dir);

    openLog(dir);
    logMsg(L"=== stamp-product-name pid=%lu exe=\"%ls\" name=\"%ls\" silent=%d ===",
           pid, exe, name, silent);

    waitForProcess(pid);

    if (!canWriteDir(dir)) {
        if (!isElevated()) {
            logMsg(L"\"%ls\" 不可写，请求提权", dir);
            closeLog();
            if (restartElevated(argc, argv)) return EXIT_OK;
            openLog(dir);
            logMsg(L"提权被拒或无法启动");
        } else {
            logMsg(L"提权后仍不可写");
        }
        /* 改不了也要把 DJCat 拉回来，别让用户以为软件没了。*/
        relaunchApp(exe, dir, silent);
        closeLog();
        return EXIT_NOT_WRITABLE;
    }

    if (stampProductName(exe, name))
        logMsg(L"产品名已改为 \"%ls\"", name);
    else
        logMsg(L"改名失败，exe 保持原样");

    relaunchApp(exe, dir, silent);
    logMsg(L"=== stamp finished ===\n");
    closeLog();
    return EXIT_OK;
}

int wmain(int argc, wchar_t *argv[]) {
    if (argc >= 2 && wcscmp(argv[1], L"--stamp-product-name") == 0)
        return stampMode(argc, argv);
    if (argc < 5) {
        fwprintf(stderr,
                 L"Usage: updater.exe <pid> <app_dir> <exe_path> <staging_dir>\n");
        return EXIT_BAD_ARGS;
    }

    DWORD pid = (DWORD)_wtoi(argv[1]);
    wchar_t appDir[PATH_BUF], exePath[PATH_BUF], stagingDir[PATH_BUF];
    formatPath(appDir, PATH_BUF, L"%ls", argv[2]);
    formatPath(exePath, PATH_BUF, L"%ls", argv[3]);
    formatPath(stagingDir, PATH_BUF, L"%ls", argv[4]);
    normalizeSeparators(appDir);
    normalizeSeparators(exePath);
    normalizeSeparators(stagingDir);
    stripTrailingSlashes(appDir);
    stripTrailingSlashes(stagingDir);

    int relocated = relocateOutOfAppDir(appDir, argc, argv);
    if (relocated > 0) return EXIT_OK;

    wchar_t selfDir[PATH_BUF];
    if (GetModuleFileNameW(NULL, selfDir, PATH_BUF)) {
        selfDir[PATH_BUF - 1] = L'\0';
        directoryOf(selfDir);
    } else {
        formatPath(selfDir, PATH_BUF, L"%ls", appDir);
    }
    openLog(selfDir);

    logMsg(L"=== DJCat updater started ===");
    logMsg(L"pid=%lu appDir=\"%ls\" exe=\"%ls\" staging=\"%ls\"",
           pid, appDir, exePath, stagingDir);
    if (relocated < 0) {
        logMsg(L"could not relocate out of the install directory");
        writeFailureMarker(appDir, L"更新器无法从安装目录移出");
        closeLog();
        return EXIT_SWAP_FAILED;
    }

    waitForProcess(pid);

    /* The staged tree must be able to replace the install, or nothing moves. */
    wchar_t stagedExe[PATH_BUF];
    formatPath(stagedExe, PATH_BUF, L"%ls\\%ls", stagingDir, baseNameOf(exePath));
    if (!hasDir(stagingDir) || !hasFile(stagedExe)) {
        logMsg(L"staged tree has no \"%ls\", refusing to swap", stagedExe);
        writeFailureMarker(appDir, L"更新包内容不完整");
        closeLog();
        return EXIT_STAGING_INVALID;
    }

    wchar_t parentDir[PATH_BUF];
    formatPath(parentDir, PATH_BUF, L"%ls", appDir);
    directoryOf(parentDir);
    if (!canWriteDir(parentDir)) {
        if (!isElevated()) {
            logMsg(L"\"%ls\" is not writable, asking for elevation", parentDir);
            closeLog();
            /* The elevated copy runs from %TEMP%, so it does not relocate again. */
            if (restartElevated(argc, argv)) return EXIT_OK;
            openLog(selfDir);
            logMsg(L"elevation was declined or could not be started");
        } else {
            logMsg(L"\"%ls\" is not writable even when elevated", parentDir);
        }
        writeFailureMarker(appDir, L"安装目录不可写，更新未执行");
        closeLog();
        return EXIT_NOT_WRITABLE;
    }

    wchar_t stagedDir[PATH_BUF], backupDir[PATH_BUF], portableInApp[PATH_BUF];
    formatPath(stagedDir, PATH_BUF, L"%ls.new", appDir);
    formatPath(backupDir, PATH_BUF, L"%ls.backup", appDir);
    formatPath(portableInApp, PATH_BUF, L"%ls\\DJCatPro", appDir);
    deleteTree(stagedDir);
    deleteTree(backupDir);

    /* The staged tree sits under Updata\, inside the directory being renamed. */
    if (!moveTree(stagingDir, stagedDir)) {
        logMsg(L"could not move the staged tree out of the install directory");
        writeFailureMarker(appDir, g_moveLocked ? LOCKED_REASON : L"无法移动更新包");
        closeLog();
        return EXIT_SWAP_FAILED;
    }

    BOOL hasPortableData = hasDir(portableInApp);
    BOOL installed = installStagedTree(appDir, stagedDir, backupDir, hasPortableData);

    if (!installed) {
        logMsg(L"install failed, the previous version is untouched");
        writeFailureMarker(appDir, g_moveLocked ? LOCKED_REASON
                                                : L"更新安装失败，已保留原版本");
        deleteTree(stagedDir);
    } else {
        logMsg(L"installed");
        if (!deleteTree(backupDir))
            logMsg(L"could not remove \"%ls\", it is safe to delete by hand",
                   backupDir);
    }

    /* 反弹窗拦截开着时，换完整目录后产品名又成了诚实名；重启前顺带重套，省一次重启。*/
    if (installed && argc > 5 && argv[5][0] != L'\0') {
        logMsg(L"反弹窗拦截：更新后把产品名重套为 \"%ls\"", argv[5]);
        if (!stampProductName(exePath, argv[5]))
            logMsg(L"重套产品名失败，产品名保持为新版本默认值");
    }

    int status = installed ? EXIT_OK : EXIT_SWAP_FAILED;
    /* Client Update 由用户点「立即更新」触发，重启照常显示窗口。*/
    if (!relaunchApp(exePath, appDir, FALSE) && status == EXIT_OK)
        status = EXIT_LAUNCH_FAILED;

    logMsg(L"=== updater finished (exit %d) ===\n", status);
    closeLog();

    /* The log lives beside the relocated updater; leave a copy where users look. */
    wchar_t logInApp[PATH_BUF];
    formatPath(logInApp, PATH_BUF, L"%ls\\updater.log", appDir);
    if (_wcsicmp(logInApp, g_logPath) != 0)
        CopyFileW(g_logPath, logInApp, FALSE);
    return status;
}
