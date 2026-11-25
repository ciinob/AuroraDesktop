#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <unknwn.h>
#include <ocidl.h>
#include <oleauto.h>
#include <stdint.h>
#include <wchar.h>

// Official Windows SDK xamlom.h definitions (64-bit exact ABI)
typedef unsigned long long InstanceHandle;

typedef enum VisualMutationType {
    Add = 0,
    Remove = 1
} VisualMutationType;

typedef enum BaseValueSource {
    BaseValueSourceUnknown = 0,
    BaseValueSourceDefault = 1,
    BaseValueSourceBuiltInStyle = 2,
    BaseValueSourceStyle = 3,
    BaseValueSourceLocal = 4
} BaseValueSource;

typedef enum VisualElementState {
    ErrorResolved = 0,
    ErrorResourceNotFound = 1,
    ErrorInvalidResource = 2
} VisualElementState;

typedef struct VisualElement {
    InstanceHandle Handle;
    InstanceHandle SrcInfoFileName; // Note: SourceInfo struct in xamlom.h! Wait - let's match SourceInfo exact layout!
} VisualElement_Dummy;

// Exact SourceInfo & VisualElement & PropertyChainValue structs from Windows 10/11 SDK <xamlom.h>
typedef struct SourceInfo {
    BSTR FileName;
    unsigned int LineNumber;
    unsigned int ColumnNumber;
    unsigned int CharacterPosition;
    BSTR Hash;
} SourceInfo;

typedef struct VisualElementReal {
    InstanceHandle Handle;
    SourceInfo SrcInfo;
    BSTR Type;
    BSTR Name;
    unsigned int NumChildren;
} VisualElementReal;

typedef struct PropertyChainSource {
    InstanceHandle Handle;
    BSTR TargetType;
    BSTR Name;
    BaseValueSource Source;
    SourceInfo SrcInfo;
} PropertyChainSource;

typedef enum MetadataBit {
    None = 0x0,
    IsValueHandle = 0x1,
    IsPropertyReadOnly = 0x2,
    IsValueCollection = 0x4,
    IsValueCollectionReadOnly = 0x8,
    IsValueBindingExpression = 0x10,
    IsValueNull = 0x20,
    IsValueHandleAndEvaluatedValue = 0x40
} MetadataBit;

typedef struct PropertyChainValue {
    unsigned int Index;
    BSTR Type;
    BSTR DeclaringType;
    BSTR ValueType;
    BSTR ItemType;
    BSTR Value;
    BOOL Overridden;
    long long MetadataBits;
    BSTR PropertyName;
    unsigned int PropertyChainIndex;
} PropertyChainValue;

typedef struct EnumType {
    BSTR Name;
    SAFEARRAY *ValueInts;
    SAFEARRAY *ValueStrings;
} EnumType;

// {AA7A8931-80E4-4FEC-8F3B-553F87B4966E}
static const GUID IID_IVisualTreeServiceCallback_Local =
    {0xAA7A8931, 0x80E4, 0x4FEC, {0x8F, 0x3B, 0x55, 0x3F, 0x87, 0xB4, 0x96, 0x6E}};

// {BAD9EB88-AE77-4397-B948-5FA2DB0A19EA}
static const GUID IID_IVisualTreeServiceCallback2_Local =
    {0xBAD9EB88, 0xAE77, 0x4397, {0xB9, 0x48, 0x5F, 0xA2, 0xDB, 0x0A, 0x19, 0xEA}};

// {A593B11A-D17F-48BB-8F66-83910731C8A5}
static const GUID IID_IVisualTreeService_Local =
    {0xA593B11A, 0xD17F, 0x48BB, {0x8F, 0x66, 0x83, 0x91, 0x07, 0x31, 0xC8, 0xA5}};

// Custom CLSID for AuroraTaskbarTAP: {D4E8A9B2-71F3-4C6D-9A2E-8B5F1C3D4E60}
static const GUID CLSID_AuroraTaskbarTAP =
    {0xD4E8A9B2, 0x71F3, 0x4C6D, {0x9A, 0x2E, 0x8B, 0x5F, 0x1C, 0x3D, 0x4E, 0x60}};

MIDL_INTERFACE("AA7A8931-80E4-4FEC-8F3B-553F87B4966E")
IVisualTreeServiceCallback_Local : public IUnknown {
public:
    virtual HRESULT STDMETHODCALLTYPE OnVisualTreeChange(
        InstanceHandle parent,
        VisualElementReal element,
        VisualMutationType mutationType) = 0;
};

MIDL_INTERFACE("BAD9EB88-AE77-4397-B948-5FA2DB0A19EA")
IVisualTreeServiceCallback2_Local : public IVisualTreeServiceCallback_Local {
public:
    virtual HRESULT STDMETHODCALLTYPE OnElementStateChanged(
        InstanceHandle element,
        VisualElementState elementState,
        LPCWSTR context) = 0;
};

MIDL_INTERFACE("A593B11A-D17F-48BB-8F66-83910731C8A5")
IVisualTreeService_Local : public IUnknown {
public:
    virtual HRESULT STDMETHODCALLTYPE AdviseVisualTreeChange(IVisualTreeServiceCallback_Local *pCallback) = 0;
    virtual HRESULT STDMETHODCALLTYPE UnadviseVisualTreeChange(IVisualTreeServiceCallback_Local *pCallback) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetEnums(unsigned int *pCount, EnumType **ppEnums) = 0;
    virtual HRESULT STDMETHODCALLTYPE CreateInstance(BSTR typeName, BSTR value, InstanceHandle *pInstanceHandle) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetPropertyValuesChain(
        InstanceHandle instanceHandle,
        unsigned int *pSourceCount,
        PropertyChainSource **ppPropertySources,
        unsigned int *pPropertyCount,
        PropertyChainValue **ppPropertyValues) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetProperty(InstanceHandle instanceHandle, InstanceHandle value, unsigned int propertyIndex) = 0;
    virtual HRESULT STDMETHODCALLTYPE ClearProperty(InstanceHandle instanceHandle, unsigned int propertyIndex) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCollectionCount(InstanceHandle instanceHandle, unsigned int *pCollectionSize) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCollectionElements(InstanceHandle instanceHandle, unsigned int startIndex, unsigned int *pElementCount, VisualElementReal **ppElementValues) = 0;
    virtual HRESULT STDMETHODCALLTYPE AddChild(InstanceHandle parent, InstanceHandle child, unsigned int index) = 0;
    virtual HRESULT STDMETHODCALLTYPE RemoveChild(InstanceHandle parent, unsigned int index) = 0;
    virtual HRESULT STDMETHODCALLTYPE ClearChildren(InstanceHandle parent) = 0;
};

// Shared memory control block mapped between AuroraDesktop.exe and Explorer XAML thread
#pragma pack(push, 1)
struct AuroraSharedTaskbarConfig {
    uint32_t version;
    uint32_t mode;       // 0 = Clear (0.0), 1 = Light Glass (0.28), 2 = Deep Aurora Glass (0.62), 3 = System Default
    uint32_t show_line;  // 0 = hide top 1px stroke, 1 = show top 1px stroke
    uint32_t reserved;
};
#pragma pack(pop)

static HANDLE g_hMapFile = NULL;
static AuroraSharedTaskbarConfig *g_pShared = NULL;
static uint32_t g_lastAppliedVersion = 0;

static IVisualTreeService_Local *g_pVts = NULL;
static UINT_PTR g_uiTimerId = 0;

#define MAX_TRACKED_HANDLES 32
static InstanceHandle g_bgFills[MAX_TRACKED_HANDLES] = {0};
static int g_bgFillCount = 0;
static InstanceHandle g_bgStrokes[MAX_TRACKED_HANDLES] = {0};
static int g_bgStrokeCount = 0;

static void AddHandle(InstanceHandle *arr, int *count, InstanceHandle h) {
    for (int i = 0; i < *count; ++i) {
        if (arr[i] == h) return;
    }
    if (*count < MAX_TRACKED_HANDLES) {
        arr[(*count)++] = h;
    }
}

static void RemoveHandle(InstanceHandle *arr, int *count, InstanceHandle h) {
    for (int i = 0; i < *count; ++i) {
        if (arr[i] == h) {
            arr[i] = arr[*count - 1];
            (*count)--;
            return;
        }
    }
}

static void EnsureSharedMemory() {
    if (g_pShared) return;
    g_hMapFile = OpenFileMappingW(FILE_MAP_READ, FALSE, L"Local\\AuroraTaskbarSharedState_v1");
    if (!g_hMapFile) {
        g_hMapFile = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, sizeof(AuroraSharedTaskbarConfig), L"Local\\AuroraTaskbarSharedState_v1");
    }
    if (g_hMapFile) {
        g_pShared = (AuroraSharedTaskbarConfig *)MapViewOfFile(g_hMapFile, FILE_MAP_READ, 0, 0, sizeof(AuroraSharedTaskbarConfig));
    }
}

static int FindOpacityPropertyIndex(InstanceHandle handle) {
    if (!g_pVts || !handle) return -1;
    unsigned int srcCount = 0;
    PropertyChainSource *pSources = NULL;
    unsigned int propCount = 0;
    PropertyChainValue *pProps = NULL;

    HRESULT hr = g_pVts->GetPropertyValuesChain(handle, &srcCount, &pSources, &propCount, &pProps);
    if (FAILED(hr)) return -1;

    int foundIdx = -1;
    for (unsigned int i = 0; i < propCount; ++i) {
        if (pProps[i].PropertyName && wcscmp(pProps[i].PropertyName, L"Opacity") == 0) {
            foundIdx = (int)pProps[i].Index;
            break;
        }
    }

    if (pSources) {
        for (unsigned int i = 0; i < srcCount; ++i) {
            if (pSources[i].TargetType) SysFreeString(pSources[i].TargetType);
            if (pSources[i].Name) SysFreeString(pSources[i].Name);
            if (pSources[i].SrcInfo.FileName) SysFreeString(pSources[i].SrcInfo.FileName);
            if (pSources[i].SrcInfo.Hash) SysFreeString(pSources[i].SrcInfo.Hash);
        }
        CoTaskMemFree(pSources);
    }
    if (pProps) {
        for (unsigned int i = 0; i < propCount; ++i) {
            if (pProps[i].Type) SysFreeString(pProps[i].Type);
            if (pProps[i].DeclaringType) SysFreeString(pProps[i].DeclaringType);
            if (pProps[i].ValueType) SysFreeString(pProps[i].ValueType);
            if (pProps[i].ItemType) SysFreeString(pProps[i].ItemType);
            if (pProps[i].Value) SysFreeString(pProps[i].Value);
            if (pProps[i].PropertyName) SysFreeString(pProps[i].PropertyName);
        }
        CoTaskMemFree(pProps);
    }
    return foundIdx;
}

static void SetElementOpacity(InstanceHandle handle, const wchar_t *opacityStr, bool restoreDefault) {
    if (!g_pVts || !handle) return;
    int propIdx = FindOpacityPropertyIndex(handle);
    if (propIdx < 0) return;

    if (restoreDefault) {
        g_pVts->ClearProperty(handle, (unsigned int)propIdx);
        return;
    }

    BSTR bType = SysAllocString(L"Double");
    BSTR bVal = SysAllocString(opacityStr);
    InstanceHandle hVal = 0;
    if (SUCCEEDED(g_pVts->CreateInstance(bType, bVal, &hVal)) && hVal != 0) {
        g_pVts->SetProperty(handle, hVal, (unsigned int)propIdx);
    }
    SysFreeString(bType);
    SysFreeString(bVal);
}

static void ApplyCurrentStateToAll() {
    EnsureSharedMemory();
    uint32_t mode = 0;      // Default Clear
    uint32_t showLine = 0;  // Default no line
    if (g_pShared) {
        mode = g_pShared->mode;
        showLine = g_pShared->show_line;
        g_lastAppliedVersion = g_pShared->version;
    }

    const wchar_t *fillOpacity = L"0.0";
    bool restoreFill = false;
    if (mode == 0) {
        fillOpacity = L"0.0";
    } else if (mode == 1) {
        fillOpacity = L"0.32";
    } else if (mode == 2) {
        fillOpacity = L"0.68";
    } else {
        restoreFill = true;
    }

    for (int i = 0; i < g_bgFillCount; ++i) {
        SetElementOpacity(g_bgFills[i], fillOpacity, restoreFill);
    }

    bool restoreStroke = (mode == 3) || (showLine != 0);
    for (int i = 0; i < g_bgStrokeCount; ++i) {
        SetElementOpacity(g_bgStrokes[i], L"0.0", restoreStroke);
    }
}

static VOID CALLBACK XamlUiPollTimerProc(HWND hwnd, UINT uMsg, UINT_PTR idEvent, DWORD dwTime) {
    EnsureSharedMemory();
    if (g_pShared && g_pShared->version != g_lastAppliedVersion) {
        ApplyCurrentStateToAll();
    }
}

class AuroraTaskbarTap : public IObjectWithSite, public IVisualTreeServiceCallback2_Local {
    volatile LONG m_refCount;
    IUnknown *m_pSite;

public:
    AuroraTaskbarTap() : m_refCount(1), m_pSite(NULL) {}
    virtual ~AuroraTaskbarTap() {
        if (m_pSite) m_pSite->Release();
    }

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IObjectWithSite)) {
            *ppv = static_cast<IObjectWithSite *>(this);
        } else if (IsEqualIID(riid, IID_IVisualTreeServiceCallback_Local) ||
                   IsEqualIID(riid, IID_IVisualTreeServiceCallback2_Local)) {
            *ppv = static_cast<IVisualTreeServiceCallback2_Local *>(this);
        } else {
            *ppv = NULL;
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }

    STDMETHODIMP_(ULONG) AddRef() override {
        return InterlockedIncrement(&m_refCount);
    }

    STDMETHODIMP_(ULONG) Release() override {
        LONG c = InterlockedDecrement(&m_refCount);
        if (c == 0) delete this;
        return c;
    }

    // IObjectWithSite
    STDMETHODIMP SetSite(IUnknown *pUnkSite) override {
        if (m_pSite) {
            if (g_pVts) {
                g_pVts->UnadviseVisualTreeChange(this);
                g_pVts->Release();
                g_pVts = NULL;
            }
            m_pSite->Release();
            m_pSite = NULL;
        }
        m_pSite = pUnkSite;
        if (m_pSite) {
            m_pSite->AddRef();
            if (SUCCEEDED(m_pSite->QueryInterface(IID_IVisualTreeService_Local, (void **)&g_pVts)) && g_pVts) {
                EnsureSharedMemory();
                g_pVts->AdviseVisualTreeChange(this);
            }
        }
        return S_OK;
    }

    STDMETHODIMP GetSite(REFIID riid, void **ppvSite) override {
        if (!m_pSite) return E_FAIL;
        return m_pSite->QueryInterface(riid, ppvSite);
    }

    // IVisualTreeServiceCallback
    STDMETHODIMP OnVisualTreeChange(
        InstanceHandle parent,
        VisualElementReal element,
        VisualMutationType mutationType) override {
        if (g_uiTimerId == 0) {
            // Schedule lightweight 250ms poll directly on Explorer's XAML UI thread!
            g_uiTimerId = SetTimer(NULL, 0, 250, XamlUiPollTimerProc);
        }

        if (element.Name && element.Type) {
            if (wcscmp(element.Type, L"Windows.UI.Xaml.Shapes.Rectangle") == 0) {
                if (wcscmp(element.Name, L"BackgroundFill") == 0) {
                    if (mutationType == Add) {
                        AddHandle(g_bgFills, &g_bgFillCount, element.Handle);
                        ApplyCurrentStateToAll();
                    } else {
                        RemoveHandle(g_bgFills, &g_bgFillCount, element.Handle);
                    }
                } else if (wcscmp(element.Name, L"BackgroundStroke") == 0) {
                    if (mutationType == Add) {
                        AddHandle(g_bgStrokes, &g_bgStrokeCount, element.Handle);
                        ApplyCurrentStateToAll();
                    } else {
                        RemoveHandle(g_bgStrokes, &g_bgStrokeCount, element.Handle);
                    }
                }
            }
        }
        return S_OK;
    }

    STDMETHODIMP OnElementStateChanged(
        InstanceHandle element,
        VisualElementState elementState,
        LPCWSTR context) override {
        return S_OK;
    }
};

class AuroraTapFactory : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void **ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *ppv = static_cast<IClassFactory *>(this);
            return S_OK;
        }
        *ppv = NULL;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }

    STDMETHODIMP CreateInstance(IUnknown *pUnkOuter, REFIID riid, void **ppvObject) override {
        if (pUnkOuter) return CLASS_E_NOAGGREGATION;
        AuroraTaskbarTap *tap = new AuroraTaskbarTap();
        HRESULT hr = tap->QueryInterface(riid, ppvObject);
        tap->Release();
        return hr;
    }
    STDMETHODIMP LockServer(BOOL fLock) override { return S_OK; }
};

static AuroraTapFactory g_Factory;

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID *ppv) {
    if (IsEqualCLSID(rclsid, CLSID_AuroraTaskbarTAP)) {
        return g_Factory.QueryInterface(riid, ppv);
    }
    return CLASS_E_CLASSNOTAVAILABLE;
}

extern "C" __declspec(dllexport) HRESULT STDAPICALLTYPE DllCanUnloadNow(void) {
    return S_FALSE;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
    }
    return TRUE;
}
