/*
 * mini_certutil.c - "certutil -hashfile <path> SHA256", the one thing the kit's installers ask certutil for.
 *
 * Wine ships certutil.exe as a stub that prints nothing (and fc.exe is a stub too), so the Windows installers
 * cannot be tested under Wine without a real hash tool: iw4x32/tools/bat_test.sh compiles this with the same
 * MSVC the project uses and puts it in the kit folder as certutil.exe (cmd finds it in the current directory
 * before the stub). Output shape follows certutil: a header line, the hex digest, a trailer.
 *
 *   "$HOME/.msvc/bin/x86/cl.exe" /O2 /W3 iw4x32/tools/mini_certutil.c advapi32.lib /Fe:.../certutil.exe
 */
#include <windows.h>
#include <wincrypt.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *path = NULL;
    for (int i = 1; i < argc; ++i)
    {
        if (_stricmp(argv[i], "-hashfile") == 0 && i + 1 < argc)
            path = argv[++i];
    }
    if (!path)
    {
        fprintf(stderr, "usage: certutil -hashfile <file> SHA256\n");
        return 1;
    }

    HANDLE file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (file == INVALID_HANDLE_VALUE)
    {
        fprintf(stderr, "Certutil: File does not exist or is locked: %s\n", path);
        return 2;
    }

    HCRYPTPROV prov = 0;
    HCRYPTHASH hash = 0;
    if (!CryptAcquireContext(&prov, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) ||
        !CryptCreateHash(prov, CALG_SHA_256, 0, 0, &hash))
    {
        fprintf(stderr, "Certutil: could not create a SHA-256 hash object\n");
        CloseHandle(file);
        return 3;
    }

    BYTE buf[65536];
    DWORD got = 0;
    BOOL ok = TRUE;
    while ((ok = ReadFile(file, buf, sizeof buf, &got, NULL)) != FALSE && got > 0)
    {
        if (!CryptHashData(hash, buf, got, 0))
        {
            ok = FALSE;
            break;
        }
    }
    CloseHandle(file);
    if (!ok)
    {
        fprintf(stderr, "Certutil: read failed\n");
        CryptDestroyHash(hash);
        CryptReleaseContext(prov, 0);
        return 4;
    }

    DWORD len = 32, cbData = 0;
    if (!CryptGetHashParam(hash, HP_HASHVAL, NULL, &len, 0))
    {
        CryptDestroyHash(hash);
        CryptReleaseContext(prov, 0);
        return 5;
    }
    BYTE digest[64] = {0};
    cbData = len;
    if (!CryptGetHashParam(hash, HP_HASHVAL, digest, &cbData, 0))
    {
        CryptDestroyHash(hash);
        CryptReleaseContext(prov, 0);
        return 6;
    }
    CryptDestroyHash(hash);
    CryptReleaseContext(prov, 0);

    printf("SHA256 hash of file %s:\n", path);
    for (DWORD i = 0; i < cbData; ++i)
        printf("%02x", digest[i]);
    printf("\nCertutil: Done.\n");
    return 0;
}
