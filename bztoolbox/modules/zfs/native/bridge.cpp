#include <windows.h>
#include <lzo1x.h>
#include <lzo1y.h>

// Workspace memory needed for LZO1X-1 compression
#define HEAP_ALLOC(var,size) \
    lzo_align_t __LZO_MMODEL var [ ((size) + (sizeof(lzo_align_t) - 1)) / sizeof(lzo_align_t) ]

static HEAP_ALLOC(wrkmem, LZO1X_1_MEM_COMPRESS);

extern "C" {
    __declspec(dllexport) int __stdcall lzo_init_dll() {
        return lzo_init();
    }

    // Compression function for the Packer
    __declspec(dllexport) int __stdcall compress_buffer(
        const unsigned char* src,
        lzo_uint src_len,
        unsigned char* dst,
        lzo_uint* dst_len
    ) {
        // Uses LZO1X-1 as seen in standard ZFS tools
        return lzo1x_1_compress(src, src_len, dst, dst_len, wrkmem);
    }

    __declspec(dllexport) int __stdcall decompress_buffer(
        int type,
        const unsigned char* src,
        lzo_uint src_len,
        unsigned char* dst,
        lzo_uint* dst_len
    ) {
        if (!src || !dst || !dst_len) return -1; // Safety check
        if (src_len == 0) return -1;

        if (type == 2) { // ZFSFLAG_1X_COMPRESSED
            return lzo1x_decompress_safe(src, src_len, dst, dst_len, NULL);
        }
        else if (type == 4) { // ZFSFLAG_1Y_COMPRESSED
            return lzo1y_decompress_safe(src, src_len, dst, dst_len, NULL);
        }
        return -100;
    }
}
