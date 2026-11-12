// IW4x-32: the D3D9 shader bytecode -> SPIR-V conversion and the module cache.
//
// PRIVATE - not for publication.
//
// One job in four steps, each of which says what it saw:
//
//   read     the shader-model 3.0 program the asset carries. A D3D9 program IS its token stream: it
//            starts with the version token d3d9types.h builds (D3DPS_VERSION / D3DVS_VERSION =
//            0xFFFF0300 / 0xFFFE0300 for 3.0) and ends with the end token (D3DPS_END = 0x0000FFFF);
//            the "PS  " / "VS  " container the D3DX effect layer wraps a program in is stepped over
//            when it is there. Tokens are walked with the layout that header documents - opcode in
//            [15:0], operand DWORD count in [27:24], opcode-specific control in [23:16], comment
//            length in [30:16] - and operand tokens with its split register-type field
//            ([30:28] and [12:11]). Nothing is skipped: a dcl, a comment or a def whose operands run
//            past the bytes the asset gave is a refusal naming what was seen.
//   convert  the SPIR-V module for what was read. The host built here translates the programs whose
//            body is a straight register copy - dcl_*, def cN, mov, end - and refuses any other
//            token by number. The words are written by hand to the SPIR-V 1.0 module layout
//            (magic 0x07230203, OpCapability Shader, Logical/GLSL450, one entry point, an
//            OpExecutionMode the stage allows, v4f32 Input/Output variables, OpAccessChain + OpLoad
//            per component read, OpCompositeInsert per masked lane, OpStore, OpReturn), because no
//            SPIR-V producer is vendored in this checkout. iw4x32/tools/vulkan_shader_probe.sh proves
//            those words with spirv-val - and proves the probe sees a bad case by failing on a
//            deliberately wrong word.
//   cache    by a hash of the bytecode bytes plus the stage, so a program never converts twice.
//   module   vkCreateShaderModule for those words through the device's own vkGetInstanceProcAddr (no
//            Vulkan loader is linked, exactly as in VulkanResources.cpp), vkDestroyShaderModule on
//            the way out, and both counted for iw4x32_vkshader.
//
// What a pass here does NOT mean, stated once and not to be over-read:
//   - It does not mean the game's shaders are translated. A lighting or post-processing program
//     reaches a token this host does not translate (a texld, an add, an if), and that refusal is
//     counted and named: a half-translated module is a wrong picture, not a failure.
//   - A VkShaderModule is a compiled program, not a frame. The pipeline, the descriptors, the
//     constant-buffer layout that CTAB describes and the per-stage interface belong to the later
//     phases of the epic; the reader hands back ShaderFacts as well as words so those phases can be
//     written against what the shader really declares.
//   - The location numbers this file hands out are its own (see output_slot), not the contract the
//     pipeline will bind to. They are stable per shader, which is what a cache needs.

#include "VulkanShaderCompiler.hpp"

#include <cstdio>
#include <cstring>
#include <vector>

namespace VulkanShaderCompiler
{
  namespace
  {
    // ---------------------------------------------------------------------------------------
    // Logging and reasons, as VulkanResources.cpp does it: stdout under this file's own name,
    // and a reason the caller may keep until the next call made here.
    // ---------------------------------------------------------------------------------------

    const char* stage_name_of(const Stage stage)
    {
      return stage == Stage::Vertex ? "vertex" : "pixel";
    }

    const char* result_name_of(const VkResult result)
    {
      switch (result)
      {
      case VK_SUCCESS: return "VK_SUCCESS";
      case VK_ERROR_OUT_OF_DEVICE_MEMORY: return "VK_ERROR_OUT_OF_DEVICE_MEMORY";
      case VK_ERROR_OUT_OF_HOST_MEMORY: return "VK_ERROR_OUT_OF_HOST_MEMORY";
      case VK_ERROR_TOO_MANY_OBJECTS: return "VK_ERROR_TOO_MANY_OBJECTS";
      case VK_ERROR_INVALID_EXTERNAL_HANDLE: return "VK_ERROR_INVALID_EXTERNAL_HANDLE";
      case VK_ERROR_INITIALIZATION_FAILED: return "VK_ERROR_INITIALIZATION_FAILED";
      case VK_ERROR_FEATURE_NOT_PRESENT: return "VK_ERROR_FEATURE_NOT_PRESENT";
      case VK_ERROR_VALIDATION_FAILED_EXT: return "VK_ERROR_VALIDATION_FAILED_EXT";
      case VK_ERROR_DEVICE_LOST: return "VK_ERROR_DEVICE_LOST";
      default: return "a VkResult this file does not name";
      }
    }

    void log_value(const char* what)
    {
      printf("iw4x32 vulkan shaders: %s\n", what);
    }

    void log_shader(const char* what, const std::uint64_t hash, const std::size_t bytes, const Stage stage)
    {
      printf("iw4x32 vulkan shaders: %s hash 0x%016llx %llu byte(s) %s\n", what,
             static_cast<unsigned long long>(hash), static_cast<unsigned long long>(bytes), stage_name_of(stage));
    }

    void log_result(const char* what, const VkResult result)
    {
      printf("iw4x32 vulkan shaders: %s -> %d (%s)\n", what, static_cast<int>(result), result_name_of(result));
    }

    char g_Reason[256];

    const char* reason_text(const char* reason)
    {
      return reason;
    }

    // Every refusal in this file ends here. A bool function that ends in `return refuse(error, reason_text("...")`
    // returns a pointer, which converts to TRUE - a refusal that reads as a success - so the reason
    // goes into the caller's pointer and the answer comes back false.
    bool refuse(const char** error, const char* reason)
    {
      if (error != nullptr)
        *error = reason;
      return false;
    }

    // A reason that names numbers this file only knows at call time. The format checks of both
    // compilers read these calls, so the arguments go through as the types the format asks for.
    template <typename... Args>
    const char* reason_fmt(const char* format, Args... args)
    {
      snprintf(g_Reason, sizeof(g_Reason), format, args...);
      return g_Reason;
    }

    // ---------------------------------------------------------------------------------------
    // The D3D9 token layout. These numbers mirror deps/dxsdk/Include/d3d9types.h (D3DSI_*,
    // D3DSIO_*, D3DSPR_*, D3DSP_*); iw4x32/tools/vulkan_shader_probe.sh greps the same numbers out
    // of that header and fails when this file and the vendored SDK stop agreeing, so a wrong number
    // here is caught instead of quietly parsing real shaders wrong.
    // ---------------------------------------------------------------------------------------

    constexpr std::uint32_t SI_OPCODE_MASK = 0x0000FFFFU;        // D3DSI_OPCODE_MASK
    constexpr std::uint32_t SI_INSTLENGTH_SHIFT = 24U;           // D3DSI_INSTLENGTH_SHIFT
    constexpr std::uint32_t SI_COMMENTSIZE_SHIFT = 16U;          // D3DSI_COMMENTSIZE_SHIFT
    constexpr std::uint32_t SI_COMMENTSIZE_MASK = 0x7FFF0000U;   // D3DSI_COMMENTSIZE_MASK

    // D3DSHADER_INSTRUCTION_OPCODE_TYPE - only the ones this file names. Anything else it meets it
    // refuses by number rather than guessing at its operands.
    constexpr std::uint16_t IO_NOP = 0U;
    constexpr std::uint16_t IO_MOV = 1U;
    constexpr std::uint16_t IO_DCL = 31U;
    constexpr std::uint16_t IO_TEXLD = 66U;
    constexpr std::uint16_t IO_DEF = 81U;
    constexpr std::uint16_t IO_COMMENT = 0xFFFEU;                // D3DSIO_COMMENT
    constexpr std::uint16_t IO_END = 0xFFFFU;                    // D3DSIO_END

    // D3DSHADER_PARAM_REGISTER_TYPE
    constexpr std::uint16_t SPR_TEMP = 0U;
    constexpr std::uint16_t SPR_INPUT = 1U;
    constexpr std::uint16_t SPR_CONST = 2U;
    constexpr std::uint16_t SPR_ADDR = 3U;
    constexpr std::uint16_t SPR_TEXTURE = 3U; // the same number as ADDR, read as a texture in a PS
    constexpr std::uint16_t SPR_RASTOUT = 4U;
    constexpr std::uint16_t SPR_ATTROUT = 5U;
    constexpr std::uint16_t SPR_OUTPUT = 6U;  // D3DSPR_TEXCRDOUT before 3.0, D3DSPR_OUTPUT from it
    constexpr std::uint16_t SPR_COLOROUT = 8U;
    constexpr std::uint16_t SPR_DEPTHOUT = 9U;
    constexpr std::uint16_t SPR_SAMPLER = 10U;
    constexpr std::uint16_t SPR_MISCTYPE = 17U;

    // Operand token fields: D3DSP_REGNUM_MASK, D3DVS_ADDRESSMODE_MASK (relative addressing),
    // D3DSP_REGTYPE_MASK2, D3DSP_WRITEMASK_ALL, D3DSPDM_SATURATE, D3DSP_SWIZZLE_MASK,
    // D3DSP_SRCMOD_MASK, and D3DSP_NOSWIZZLE (x,y,z,w = 0x1B in those two-bit groups).
    constexpr std::uint32_t SP_REGNUM_MASK = 0x000007FFU;
    constexpr std::uint32_t SP_RELATIVE_BIT = 0x00002000U;
    constexpr std::uint32_t SP_REGTYPE_SHIFT2 = 8U;   // D3DSP_REGTYPE_SHIFT2
    constexpr std::uint32_t SP_REGTYPE_MASK2 = 0x00001800U;
    constexpr std::uint32_t SP_WRITEMASK_SHIFT = 16U;
    constexpr std::uint32_t SP_WRITEMASK_MASK = 0x000F0000U;
    constexpr std::uint32_t SP_SATURATE_BIT = 0x00100000U;
    constexpr std::uint32_t SP_SRCMOD_SHIFT = 24U;
    constexpr std::uint32_t SP_SRCMOD_MASK = 0x0F000000U;
    constexpr std::uint32_t SP_NOSWIZZLE = 0x0000001BU;
    constexpr std::uint32_t DCL_TEXTURETYPE_SHIFT = 27U; // D3DSP_TEXTURETYPE_SHIFT
    constexpr std::uint32_t DCL_USAGEINDEX_SHIFT = 16U;  // D3DSP_DCL_USAGEINDEX_SHIFT
    constexpr std::uint32_t DCL_INFO_SEMANTIC_BIT = 0x80000000U; // bit 31 of a dcl info token: the
    // declaration names a semantic (usage in [4:0], usage index in [19:16]) rather than a count

    // D3DPS_VERSION(major,minor) / D3DVS_VERSION(major,minor) - the top half of the version token is
    // the stage, and a ps_3_0 program starts with 0xFFFF0300, a vs_3_0 one with 0xFFFE0300.
    constexpr std::uint32_t PS_VERSION_MARKER = 0xFFFFU;
    constexpr std::uint32_t VS_VERSION_MARKER = 0xFFFEU;

    // The SPIR-V BuiltIn token a D3D9 special register becomes under the HLSL 7.2 semantics, and the
    // marker for "no built-in": those numbers are the SPIR-V BuiltIn enumerators, and the mapping is
    // the one the HLSL 7.2 semantics of SPIR-V-V1.3 define (gl_Position, gl_VertexIndex,
    // gl_FragCoord, gl_FrontFacing). Anything without a name in that mapping keeps its register
    // number and becomes a Location.
    constexpr std::uint32_t SPIRV_NO_BUILTIN = 0xFFFFFFFFU;
    constexpr std::uint32_t SPIRV_BUILTIN_POSITION = 0U;
    constexpr std::uint32_t SPIRV_BUILTIN_FRONT_FACING = 10U;
    constexpr std::uint32_t SPIRV_BUILTIN_FRAGMENT_COORD = 15U;
    constexpr std::uint32_t SPIRV_BUILTIN_FRAG_DEPTH = 22U;
    constexpr std::uint32_t SPIRV_BUILTIN_VERTEX_INDEX = 4224U;

    // The optional container header (the "PS  " / "VS  " DXBC v2 wrapper the D3DX effect layer
    // emits): fourcc, version bytes, the program's total length in DWORDs, the token stream's length
    // in bytes - 16 bytes, so the token stream starts at word 4. CreatePixelShader takes the bare
    // token stream too, which is what a zone asset carries, so this header is detected rather than
    // assumed, and the size fields are honoured rather than trusted.
    constexpr std::size_t CONTAINER_HEADER_WORDS = 4U;

    struct Operand
    {
      std::uint16_t regType = 0U;
      std::uint32_t index = 0U;
      std::uint32_t writeMask = 0U; // destination only: x=1 y=2 z=4 w=8
      std::uint32_t swizzle = 0U;   // source only: two bits per component
      std::uint32_t srcMod = 0U;
      bool relative = false;
      bool saturate = false;
    };

    void read_operand(const std::uint32_t token, Operand& out)
    {
      // D3DSP_REGTYPE_MASK / D3DSP_REGTYPE_MASK2: the low three bits of the type live at [30:28]
      // and bit 3 and 4 of it live at [12:11], which is why the field has to be collected in two
      // halves. Read as one field, every register type above 7 (sampler, misc, label, predicate)
      // decodes to a number that does not exist.
      out.regType = static_cast<std::uint16_t>(((token >> 28U) & 0x7U) | ((token & SP_REGTYPE_MASK2) >> SP_REGTYPE_SHIFT2));
      out.index = token & SP_REGNUM_MASK;
      out.relative = (token & SP_RELATIVE_BIT) != 0U;
      out.writeMask = (token & SP_WRITEMASK_MASK) >> SP_WRITEMASK_SHIFT;
      out.saturate = (token & SP_SATURATE_BIT) != 0U;
      out.srcMod = (token & SP_SRCMOD_MASK) >> SP_SRCMOD_SHIFT;
      out.swizzle = (token >> 16U) & 0xFFU;
    }

    // The registers this layer knows how to attach to an interface variable.
    bool is_input_register(const std::uint16_t regType)
    {
      return regType == SPR_INPUT || regType == SPR_TEXTURE || regType == SPR_MISCTYPE;
    }

    bool is_output_register(const std::uint16_t regType)
    {
      return regType == SPR_OUTPUT || regType == SPR_RASTOUT || regType == SPR_ATTROUT ||
             regType == SPR_COLOROUT || regType == SPR_DEPTHOUT;
    }

    // A D3D9 register as the SPIR-V interface variable it becomes. false means this host has no
    // honest answer for it - and the refusal says which register that was, rather than letting the
    // copy go somewhere a reader would have to guess at.
    bool target_for_input(const Operand& source, const Stage stage, std::uint32_t& outBuiltIn, const char** error)
    {
      outBuiltIn = SPIRV_NO_BUILTIN;

      // vPos / vFace exist only in a pixel shader, and a pixel shader's v0..v15 are the rasterizer's
      // interpolants, which is exactly what Vulkan's Input locations are.
      if (source.regType == SPR_MISCTYPE)
      {
        if (stage != Stage::Pixel)
          return refuse(error, reason_text("a position or face register in a vertex shader is not a register "
                               "this layer knows how to name"));
        if (source.index == 0U)
          outBuiltIn = SPIRV_BUILTIN_FRAGMENT_COORD; // vPos -> gl_FragCoord
        else if (source.index == 1U)
          return refuse(error, reason_text("a copy from vFace would have to convert a bool to a float, and this "
                             "host translates no expressions"));
        else
          return refuse(error, reason_fmt("a misc register number of %u is not a register this layer names", source.index, 0U));
      }

      return true;
    }

    bool target_for_output(const Operand& destination, const Stage stage, std::uint32_t& outBuiltIn, const char** error)
    {
      outBuiltIn = SPIRV_NO_BUILTIN;

      if (destination.regType == SPR_RASTOUT)
      {
        // oPos is gl_Position in a vertex shader. oFog and oPointSize have no SPIR-V output of their
        // own - a later phase would have to emulate them - and a pixel shader writing oPos is not a
        // thing Vulkan can be asked for at all.
        if (destination.index == 0U)
        {
          if (stage != Stage::Vertex)
            return refuse(error, reason_text("a pixel shader writing oPos has no Vulkan output to write to"));
          outBuiltIn = SPIRV_BUILTIN_POSITION;
          return true;
        }

        return refuse(error, reason_fmt("the rasterizer output o%u (fog / point size) has no SPIR-V output this "
                          "layer can name", destination.index, 0U));
      }

      if (destination.regType == SPR_DEPTHOUT)
      {
        outBuiltIn = SPIRV_BUILTIN_FRAG_DEPTH;
        return true;
      }

      return true; // o0..o11 / oC0..oC3 / oD: ordinary outputs at their register number
    }

    // ---------------------------------------------------------------------------------------
    // The program: the token stream, the facts, and the register copies this host can translate.
    // ---------------------------------------------------------------------------------------

    // One end of a register copy: the D3D register number, and the built-in that number means when
    // the HLSL 7.2 mapping has a name for it.
    struct CopyTarget
    {
      std::uint32_t registerNumber = 0U;
      std::uint32_t builtIn = SPIRV_NO_BUILTIN;
    };

    struct ComponentCopy
    {
      CopyTarget source;
      std::uint32_t inputComponent = 0U; // 0..3: the mov is unswizzled, so lane n in is lane n out
      CopyTarget target;
      std::uint32_t outputComponent = 0U;
      bool integerData = false; // a0 carries integers: everything it feeds is an unsigned vector
    };

    struct Program
    {
      Stage stage = Stage::Pixel;
      unsigned int major = 0U;
      unsigned int minor = 0U;
      bool container = false;
      std::uint32_t containerDwords = 0U;

      const std::uint32_t* tokens = nullptr;
      std::size_t tokenWords = 0U;

      std::vector<ComponentCopy> copies;
    };

    bool read_version(const std::uint32_t token, Program& out)
    {
      const std::uint32_t marker = (token >> 16U) & 0xFFFFU;
      if (marker != PS_VERSION_MARKER && marker != VS_VERSION_MARKER)
        return false;

      out.stage = marker == PS_VERSION_MARKER ? Stage::Pixel : Stage::Vertex;
      out.major = (token >> 8U) & 0xFFU;
      out.minor = token & 0xFFU;
      return true;
    }

    bool find_tokens(const std::uint32_t* words, const std::size_t wordCount, Program& program, const char** error)
    {
      if (words == nullptr || wordCount == 0U)
        return refuse(error, reason_text("no shader bytecode to read"));

      std::size_t at = 0U;

      if (wordCount > CONTAINER_HEADER_WORDS)
      {
        const char* magic = reinterpret_cast<const char*>(&words[0]);
        if ((magic[0] == 'P' || magic[0] == 'V') && magic[1] == 'S' && magic[2] == ' ' && magic[3] == ' ')
        {
          const std::uint32_t containerDwords = words[2];
          const std::uint32_t codeBytes = words[3];

          if (codeBytes < 4U || (codeBytes & 3U) != 0U)
            return refuse(error, reason_fmt("the shader container declares a code size of %u bytes", codeBytes, 0U));

          const std::size_t tokenWords = codeBytes / 4U;
          if (CONTAINER_HEADER_WORDS + tokenWords > wordCount)
            return refuse(error, reason_fmt("the container says the program is %u words, the asset carries %u",
                              static_cast<unsigned>(tokenWords), static_cast<unsigned>(wordCount)));

          // The container's own total length is the other size field, and it is not the one the walk
          // uses: the token stream ends at its 0xFFFF token anyway, so a container whose two sizes
          // disagree still converts, and the disagreement is printed rather than hidden.
          if (containerDwords != wordCount)
            printf("iw4x32 vulkan shaders: the container declares %u DWORD(s) for a program the asset "
                   "carries as %u\n", containerDwords, static_cast<unsigned>(wordCount));

          program.container = true;
          program.containerDwords = containerDwords;
          at = CONTAINER_HEADER_WORDS;
        }
      }

      if (at >= wordCount)
        return refuse(error, reason_text("the bytes the asset carries hold no version token"));

      if (!read_version(words[at], program))
        return refuse(error, reason_fmt("the first token of this program is 0x%08X, not a ps_/vs_ version token", words[at], 0U));

      if (program.major != 3U)
        return refuse(error, reason_fmt("this file reads shader model 3.0 programs, this one says %u.%u", program.major, program.minor));

      ++at;
      program.tokens = words + at;
      program.tokenWords = wordCount - at;
      return true;
    }

    // Walk the token stream. Fills the facts, records the copies, and stops - naming the opcode - at
    // the first token this host cannot translate. Stopping is the reader reporting the program's
    // contents honestly, not a reader bug.
    bool walk_tokens(Program& program, ShaderFacts& facts, const char** error)
    {
      const std::uint32_t* tokens = program.tokens;
      const std::size_t count = program.tokenWords;
      std::size_t at = 0U;
      bool sawEnd = false;

      while (at < count)
      {
        const std::uint32_t token = tokens[at];
        const std::uint16_t opcode = static_cast<std::uint16_t>(token & SI_OPCODE_MASK);
        const std::uint32_t control = (token >> 16U) & 0xFFU;

        if (opcode == IO_END)
        {
          sawEnd = true;
          break;
        }

        if (opcode == IO_COMMENT)
        {
          const std::uint32_t commentWords = (token & SI_COMMENTSIZE_MASK) >> SI_COMMENTSIZE_SHIFT;
          if (at + 1U + commentWords > count)
            return refuse(error, reason_fmt("a shader comment of %u words runs past the program", commentWords, 0U));
          at += 1U + commentWords;
          continue;
        }

        const std::uint32_t operandWords = (token >> SI_INSTLENGTH_SHIFT) & 0xFU;
        if (operandWords == 0U)
          return refuse(error, reason_fmt("the token for opcode %u declares no operands", opcode, 0U));
        if (at + 1U + operandWords > count)
          return refuse(error, reason_fmt("opcode %u declares %u operand words the program does not hold", opcode, operandWords));

        const std::uint32_t* operands = tokens + at + 1U;

        if (opcode == IO_DCL)
        {
          ++facts.declarationCount;

          // A dcl is an info token and the register it declares (the "DCL Instruction Format" of the
          // D3D9 driver docs: usage in [4:0], usage index in [19:16], texture type in [30:27]).
          if (operandWords < 2U)
            return refuse(error, reason_fmt("a dcl carries %u words where an info token and a register follow", operandWords, 0U));

          const std::uint32_t info = operands[0];
          Operand destination;
          read_operand(operands[1], destination);

          const std::uint32_t usageIndex = (info >> DCL_USAGEINDEX_SHIFT) & 0xFU;
          const std::uint32_t textureType = (info >> DCL_TEXTURETYPE_SHIFT) & 0xFU;

          if (destination.regType == SPR_SAMPLER)
          {
            if ((info & DCL_INFO_SEMANTIC_BIT) == 0U)
              return refuse(error, reason_text("a dcl of a sampler register carries no semantic marker bit, so this "
                                 "file cannot tell which sampler declaration it is"));

            if (textureType != 0U && usageIndex != 0U)
              return refuse(error, reason_fmt("a dcl_2d with a texture array index of %u is not the single "
                                "sampler-plus-texture pair Vulkan's combined image sampler is", usageIndex, 0U));

            ++facts.samplerCount;
            if (destination.index < 8U)
              facts.samplerTypes |= textureType << (destination.index * 4U);
          }
          else if (destination.regType == SPR_MISCTYPE)
          {
            // vPos and vFace: declared, but not vector registers, so they stay out of inputMask and
            // are named by their own counters. A copy from vFace is refused where it is read.
            if (destination.index == 0U)
              ++facts.positionInputCount;
            else if (destination.index == 1U)
              ++facts.faceInputCount;
            else
              return refuse(error, reason_fmt("a misc register number of %u is not a register this layer names",
                                destination.index, usageIndex));
          }
          else if (destination.regType == SPR_ADDR && program.stage == Stage::Vertex)
          {
            ++facts.addressRegisterCount; // a0 (and a1) are the loop/address file, not a v register
          }
          else if (is_input_register(destination.regType))
          {
            if (destination.index >= 32U)
              return refuse(error, reason_fmt("an input register number of %u is past what this layer can map",
                                destination.index, usageIndex));
            facts.inputMask |= 1U << destination.index;
          }
          else if (is_output_register(destination.regType))
          {
            if (destination.index >= 32U)
              return refuse(error, reason_fmt("an output register number of %u is past what this layer can map",
                                destination.index, usageIndex));

            std::uint32_t builtIn = SPIRV_NO_BUILTIN;
            if (!target_for_output(destination, program.stage, builtIn, error))
            {
              facts.stoppedAtOpcode = IO_DCL;
              return false;
            }

            facts.outputMask |= 1U << destination.index;
          }
          else if (destination.regType == SPR_TEMP)
          {
            if ((info & DCL_INFO_SEMANTIC_BIT) != 0U)
              return refuse(error, reason_text("a dcl of a temp register carries a semantic, which is not what "
                                 "dcl_temps (a count) looks like"));
            facts.tempCount = destination.index; // dcl_temps carries the count in the operand
          }
          else if (destination.regType == SPR_CONST)
          {
            if ((info & DCL_INFO_SEMANTIC_BIT) != 0U)
              return refuse(error, reason_text("a dcl of a constant register carries a semantic, which is not what "
                                 "dcl_consts (a count) looks like"));
            facts.constantCount = destination.index; // dcl_consts the same way
          }
          else
          {
            facts.stoppedAtOpcode = IO_DCL;
            return refuse(error, reason_fmt("a dcl of register type %u (usage index %u) is not a register this layer connects",
                              destination.regType, usageIndex));
          }

          at += 1U + operandWords;
          continue;
        }

        // Below this line everything is an instruction, not a declaration.
        ++facts.instructionCount;

        if (opcode == IO_DEF)
        {
          if (operandWords < 5U)
            return refuse(error, reason_fmt("a def carries %u words where a register and four floats follow", operandWords, 0U));

          Operand destination;
          read_operand(operands[0], destination);
          if (destination.regType != SPR_CONST)
            return refuse(error, reason_fmt("a def writes register type %u, which is not a constant register", destination.regType, 0U));

          if (destination.index + 1U > facts.constantCount)
            facts.constantCount = destination.index + 1U;

          at += 1U + operandWords;
          continue;
        }

        if (opcode != IO_MOV)
        {
          facts.stoppedAtOpcode = opcode;
          return refuse(error, reason_fmt("this host does not translate opcode %u (control 0x%02X): the material using it is not drawn",
                            opcode, control));
        }

        Operand destination, source;
        read_operand(operands[0], destination);
        read_operand(operands[1], source);

        // The only mov translated here is a whole-register input-to-output copy: no index, no
        // modifier, no swizzle, no saturate. Anything else would need a real expression lowering,
        // and a guess there is a wrong picture rather than a missing one.
        const std::size_t movWords = 2U + (destination.relative ? 1U : 0U) + (source.relative ? 1U : 0U);
        if (operandWords != movWords || destination.relative || source.relative || source.srcMod != 0U ||
            destination.saturate || source.swizzle != SP_NOSWIZZLE)
        {
          facts.stoppedAtOpcode = IO_MOV;
          return refuse(error, reason_text("a mov this host would have to interpret (an index, a modifier or a swizzle) "
                             "is not a register copy"));
        }

        if (!is_output_register(destination.regType) || !is_input_register(source.regType))
        {
          facts.stoppedAtOpcode = IO_MOV;
          return refuse(error, reason_fmt("a mov from register type %u to register type %u is not an input-to-output copy",
                            source.regType, destination.regType));
        }

        // The address register a0 is gl_VertexIndex in a vertex shader (the HLSL 7.2 mapping). It is
        // an integer register, so any other use of it would need a conversion this host does not do.
        std::uint32_t sourceBuiltIn = SPIRV_NO_BUILTIN;
        if (source.regType == SPR_TEXTURE && program.stage == Stage::Vertex)
        {
          if (source.index != 0U)
          {
            facts.stoppedAtOpcode = IO_MOV;
            return refuse(error, reason_fmt("the address register a%u has no name in the mapping this file writes", source.index, 0U));
          }
          sourceBuiltIn = SPIRV_BUILTIN_VERTEX_INDEX;
        }
        else
        {
          if (!target_for_input(source, program.stage, sourceBuiltIn, error))
          {
            facts.stoppedAtOpcode = IO_MOV;
            return false;
          }
        }

        std::uint32_t targetBuiltIn = SPIRV_NO_BUILTIN;
        if (!target_for_output(destination, program.stage, targetBuiltIn, error))
        {
          facts.stoppedAtOpcode = IO_MOV;
          return false;
        }

        const std::uint32_t sourceNumber =
            sourceBuiltIn == SPIRV_BUILTIN_VERTEX_INDEX ? 0U : source.index; // a0 is gl_VertexIndex
        const bool integerData = sourceBuiltIn == SPIRV_BUILTIN_VERTEX_INDEX;

        for (std::uint32_t component = 0U; component < 4U; ++component)
        {
          if ((destination.writeMask & (1U << component)) == 0U)
            continue;

          ComponentCopy copy;
          copy.source.registerNumber = sourceNumber;
          copy.source.builtIn = sourceBuiltIn;
          copy.inputComponent = component;
          copy.target.registerNumber = destination.index;
          copy.target.builtIn = targetBuiltIn;
          copy.outputComponent = component;
          copy.integerData = integerData;
          program.copies.push_back(copy);

          if (destination.index < 32U)
            facts.copyMask |= 1U << destination.index;
        }

        at += 1U + operandWords;
      }

      if (!sawEnd)
        return refuse(error, reason_text("the program has no end token (0xFFFF) before its bytes run out"));

      return true;
    }

    // ---------------------------------------------------------------------------------------
    // SPIR-V module layout. Written by hand because this checkout vendors no SPIR-V producer: the
    // words follow the SPIR-V 1.0 section layout, and every id is handed out in a pre-pass so the
    // declaration block declares everything the body uses (the spec forbids a forward reference,
    // which is why the ids are counted before anything is emitted).
    // ---------------------------------------------------------------------------------------

    namespace spirv
    {
      constexpr std::uint32_t MAGIC = 0x07230203U;
      constexpr std::uint32_t VERSION_1_0 = 0x00010000U;
      // The generator word is (tool number << 16) | version. This writer is not a registered tool, so
      // it claims nothing: tool 0 (unknown), version 1. A disassembly identifies the module by its
      // entry-point name ("iw4x32_dxbc") instead.
      constexpr std::uint32_t GENERATOR = 0x00000001U;

      // Opcodes are the SPIR-V 1.0 enumerators; the probe feeds the words this writes to spirv-val,
      // so a wrong number here is a failing CHECK rather than a driver's guess.
      constexpr std::uint32_t OP_EXTENSION = 10U;
      constexpr std::uint32_t OP_CAPABILITY = 17U;
      constexpr std::uint32_t OP_MEMORY_MODEL = 14U;
      constexpr std::uint32_t OP_ENTRY_POINT = 15U;
      constexpr std::uint32_t OP_EXECUTION_MODE = 16U;
      constexpr std::uint32_t OP_DECORATE = 71U;
      constexpr std::uint32_t OP_TYPE_VOID = 19U;
      constexpr std::uint32_t OP_TYPE_INT = 21U;
      constexpr std::uint32_t OP_TYPE_FLOAT = 22U;
      constexpr std::uint32_t OP_TYPE_VECTOR = 23U;
      constexpr std::uint32_t OP_TYPE_POINTER = 32U;
      constexpr std::uint32_t OP_TYPE_FUNCTION = 33U;
      constexpr std::uint32_t OP_CONSTANT = 43U;
      constexpr std::uint32_t OP_VARIABLE = 59U;
      constexpr std::uint32_t OP_LOAD = 61U;
      constexpr std::uint32_t OP_STORE = 62U;
      constexpr std::uint32_t OP_ACCESS_CHAIN = 65U;
      constexpr std::uint32_t OP_COMPOSITE_EXTRACT = 81U;
      constexpr std::uint32_t OP_FUNCTION = 54U;
      constexpr std::uint32_t OP_FUNCTION_END = 56U;
      constexpr std::uint32_t OP_UNDEF = 1U;
      constexpr std::uint32_t OP_LABEL = 248U;
      constexpr std::uint32_t OP_RETURN = 253U;

      constexpr std::uint32_t CAP_SHADER = 1U;
      constexpr std::uint32_t MODEL_LOGICAL = 0U;
      constexpr std::uint32_t MODEL_GLSL450 = 1U;
      constexpr std::uint32_t EXEC_VERTEX = 0U;    // ExecutionModel Vertex
      constexpr std::uint32_t EXEC_FRAGMENT = 4U;  // ExecutionModel Fragment
      constexpr std::uint32_t MODE_ORIGIN_UPPER_LEFT = 7U; // ExecutionMode OriginUpperLeft
      constexpr std::uint32_t STORAGE_INPUT = 1U;
      constexpr std::uint32_t STORAGE_OUTPUT = 3U;
      constexpr std::uint32_t STORAGE_FUNCTION = 7U;
      constexpr std::uint32_t DEC_BUILT_IN = 11U;
      constexpr std::uint32_t DEC_LOCATION = 30U;

      void instruction(std::vector<std::uint32_t>& out, const std::uint32_t opcode,
                       const std::vector<std::uint32_t>& operands)
      {
        out.push_back((static_cast<std::uint32_t>(operands.size() + 1U) << 16U) | (opcode & 0xFFFFU));
        for (const std::uint32_t word : operands)
          out.push_back(word);
      }

      // A literal string as little-endian DWORDs, NUL padded to a word boundary (at least one NUL,
      // which is what the spec's "one extra character if needed" means).
      void literal_string(std::vector<std::uint32_t>& out, const char* text)
      {
        std::size_t len = 0U;
        while (text[len] != '\0')
          ++len;

        const std::size_t words = (len / 4U) + 1U;
        for (std::size_t w = 0U; w < words; ++w)
        {
          std::uint32_t word = 0U;
          for (std::size_t b = 0U; b < 4U; ++b)
          {
            const std::size_t at = w * 4U + b;
            if (at < len)
              word |= static_cast<std::uint32_t>(static_cast<unsigned char>(text[at])) << (8U * b);
          }
          out.push_back(word);
        }
      }
      // (gl_Position, gl_VertexIndex, gl_FragCoord) this file maps the D3D9 special registers to:
      // the name is recorded, and nothing else about the extension is claimed.
      void extension_hlsl_7_2(std::vector<std::uint32_t>& out)
      {
        std::vector<std::uint32_t> operands;
        literal_string(operands, "GL_HLSL_7_2");
        instruction(out, OP_EXTENSION, operands);
      }
    } // namespace spirv

    // One interface variable of the module this host emits. `integerData` picks the vector type:
    // gl_VertexIndex and gl_PointIndex are 32-bit integer interface variables in SPIR-V, and a float
    // one decorated with those built-ins is invalid, which is why the type travels with the register.
    struct InterfaceVar
    {
      std::uint32_t id = 0U;
      std::uint32_t registerNumber = 0U;
      std::uint32_t location = 0U; // the location this module gives it (0 when it is a built-in)
      std::uint32_t builtIn = SPIRV_NO_BUILTIN;
      bool integerData = false;
    };

    // One component read of one input register, loaded once however many stores want it.
    struct ReadValue
    {
      std::uint32_t inputIndex = 0U; // index into the input vars
      std::uint32_t component = 0U;
      std::uint32_t scalarId = 0U;
    };

    // One output store: the writes D3D9 would retire at the end of the shader, one per output
    // register, each carrying the components its mov write mask asked for.
    struct StorePlan
    {
      std::uint32_t outputIndex = 0U; // index into the output vars
      std::vector<std::pair<std::uint32_t, std::uint32_t>> lanes; // (component, read index)
      std::vector<std::uint32_t> insertIds;
    };

    // The SPIR-V words for the copies the reader collected. False (with a reason) when the program
    // has nothing this module can say about it.
    bool emit_spirv(const Program& program, ShaderFacts& facts, std::vector<std::uint32_t>& outSpirv,
                    const char** error)
    {
      std::vector<InterfaceVar> inputs, outputs;
      std::vector<ReadValue> reads;
      std::vector<StorePlan> stores;

      auto find_input = [&](const ComponentCopy& copy) -> std::size_t
      {
        for (std::size_t i = 0; i < inputs.size(); ++i)
          if (inputs[i].registerNumber == copy.source.registerNumber && inputs[i].builtIn == copy.source.builtIn)
            return i;
        return inputs.size();
      };

      for (const ComponentCopy& copy : program.copies)
      {
        std::size_t in = find_input(copy);
        if (in == inputs.size())
        {
          InterfaceVar var;
          var.registerNumber = copy.source.registerNumber;
          var.builtIn = copy.source.builtIn;
          var.integerData = copy.integerData;
          inputs.push_back(var);
          in = inputs.size() - 1U;
        }

        std::size_t out = outputs.size();
        for (std::size_t i = 0; i < outputs.size(); ++i)
          if (outputs[i].registerNumber == copy.target.registerNumber && outputs[i].builtIn == copy.target.builtIn)
            out = i;

        if (out == outputs.size())
        {
          InterfaceVar var;
          var.registerNumber = copy.target.registerNumber;
          var.builtIn = copy.target.builtIn;
          var.integerData = copy.integerData;
          outputs.push_back(var);
          out = outputs.size() - 1U;
        }
        else if (outputs[out].integerData != copy.integerData)
          return refuse(error, reason_text("one output is fed from both an integer register (a0) and a float one, "
                               "and this host writes no conversion between them"));

        std::size_t read = reads.size();
        for (std::size_t i = 0; i < reads.size(); ++i)
          if (reads[i].inputIndex == in && reads[i].component == copy.inputComponent)
            read = i;

        if (read == reads.size())
        {
          ReadValue value;
          value.inputIndex = static_cast<std::uint32_t>(in);
          value.component = copy.inputComponent;
          reads.push_back(value);
          read = reads.size() - 1U;
        }

        std::size_t store = stores.size();
        for (std::size_t i = 0; i < stores.size(); ++i)
          if (stores[i].outputIndex == out)
            store = i;

        if (store == stores.size())
        {
          StorePlan plan;
          plan.outputIndex = static_cast<std::uint32_t>(out);
          stores.push_back(plan);
          store = stores.size() - 1U;
        }

        stores[store].lanes.push_back(std::make_pair(copy.outputComponent, static_cast<std::uint32_t>(read)));
      }

      if (inputs.empty() || outputs.empty())
        return refuse(error, reason_text("this program copies no input straight to an output, and this host emits "
                             "nothing for a program it cannot connect"));

      // Every id is handed out before the first word is written: the module's id bound is the first
      // word after the header, the declaration block may not reference an id it has not defined, and
      // nothing may be added once the function block has started.
      std::uint32_t nextId = 1U;
      const std::uint32_t idVoid = nextId++;
      const std::uint32_t idFn = nextId++;
      const std::uint32_t idF32 = nextId++;
      const std::uint32_t idU32 = nextId++;
      const std::uint32_t idVecF = nextId++;  // float4: the ordinary v / o / t registers
      const std::uint32_t idVecU = nextId++;  // uint4: the integer ones (a0, and what it feeds)
      const std::uint32_t idPtrInF = nextId++;
      const std::uint32_t idPtrOutF = nextId++;
      const std::uint32_t idPtrInU = nextId++;
      const std::uint32_t idPtrOutU = nextId++;
      const std::uint32_t idPtrFnF = nextId++;
      const std::uint32_t idPtrFnU = nextId++;
      const std::uint32_t idPtrScalarF = nextId++;
      const std::uint32_t idPtrScalarU = nextId++;
      const std::uint32_t idMain = nextId++;
      const std::uint32_t idLabel = nextId++;
      const std::uint32_t idZero = nextId++;
      const std::uint32_t idOne = nextId++;
      const std::uint32_t idTwo = nextId++;
      const std::uint32_t idThree = nextId++;

      for (InterfaceVar& var : inputs)
      {
        var.id = nextId++;
        if (var.builtIn == SPIRV_NO_BUILTIN)
          var.location = var.registerNumber; // an ordinary v / t register: its number is its location
      }
      for (InterfaceVar& var : outputs)
      {
        var.id = nextId++;
        if (var.builtIn == SPIRV_NO_BUILTIN)
          var.location = var.registerNumber; // an ordinary o register, likewise
      }

      std::vector<std::uint32_t> loadedInput(inputs.size(), 0U);
      for (std::size_t i = 0; i < inputs.size(); ++i)
        loadedInput[i] = nextId++;

      for (ReadValue& read : reads)
        read.scalarId = nextId++;

      for (StorePlan& store : stores)
      {
        store.insertIds.clear();
        for (std::size_t lane = 0U; lane < store.lanes.size(); ++lane)
          store.insertIds.push_back(nextId++);
      }

      std::vector<std::uint32_t> undefOutput(outputs.size(), 0U);
      std::vector<std::uint32_t> localOutput(outputs.size(), 0U);
      std::vector<std::uint32_t> loadedOutput(outputs.size(), 0U);
      for (std::size_t i = 0; i < outputs.size(); ++i)
      {
        undefOutput[i] = nextId++;
        localOutput[i] = nextId++;
        loadedOutput[i] = nextId++;
      }

      std::vector<std::uint32_t>& w = outSpirv;
      w.clear();

      w.push_back(spirv::MAGIC);
      w.push_back(spirv::VERSION_1_0);
      w.push_back(spirv::GENERATOR);
      w.push_back(nextId); // id bound
      w.push_back(0U);     // schema, reserved

      spirv::instruction(w, spirv::OP_CAPABILITY, {spirv::CAP_SHADER});
      spirv::extension_hlsl_7_2(w);
      spirv::instruction(w, spirv::OP_MEMORY_MODEL, {spirv::MODEL_LOGICAL, spirv::MODEL_GLSL450});

      {
        std::vector<std::uint32_t> entry;
        entry.push_back(program.stage == Stage::Vertex ? spirv::EXEC_VERTEX : spirv::EXEC_FRAGMENT);
        entry.push_back(idMain);
        spirv::literal_string(entry, "iw4x32_dxbc");
        for (const InterfaceVar& var : inputs)
          entry.push_back(var.id);
        for (const InterfaceVar& var : outputs)
          entry.push_back(var.id);
        spirv::instruction(w, spirv::OP_ENTRY_POINT, entry);
      }

      // OriginUpperLeft is a fragment-stage mode: a vertex entry point that declared it is invalid,
      // which is the kind of thing the probe's spirv-val run catches rather than a driver.
      if (program.stage != Stage::Vertex)
        spirv::instruction(w, spirv::OP_EXECUTION_MODE, {idMain, spirv::MODE_ORIGIN_UPPER_LEFT});

      spirv::instruction(w, spirv::OP_TYPE_VOID, {idVoid});
      spirv::instruction(w, spirv::OP_TYPE_FUNCTION, {idFn, idVoid}); // no parameter list
      spirv::instruction(w, spirv::OP_TYPE_FLOAT, {idF32, 32U});
      spirv::instruction(w, spirv::OP_TYPE_INT, {idU32, 32U, 0U});
      spirv::instruction(w, spirv::OP_TYPE_VECTOR, {idVecF, idF32, 4U});
      spirv::instruction(w, spirv::OP_TYPE_VECTOR, {idVecU, idU32, 4U});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrInF, spirv::STORAGE_INPUT, idVecF});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrOutF, spirv::STORAGE_OUTPUT, idVecF});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrInU, spirv::STORAGE_INPUT, idVecU});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrOutU, spirv::STORAGE_OUTPUT, idVecU});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrFnF, spirv::STORAGE_FUNCTION, idVecF});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrFnU, spirv::STORAGE_FUNCTION, idVecU});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrScalarF, spirv::STORAGE_FUNCTION, idF32});
      spirv::instruction(w, spirv::OP_TYPE_POINTER, {idPtrScalarU, spirv::STORAGE_FUNCTION, idU32});
      spirv::instruction(w, spirv::OP_CONSTANT, {idU32, idZero, 0U});
      spirv::instruction(w, spirv::OP_CONSTANT, {idU32, idOne, 1U});
      spirv::instruction(w, spirv::OP_CONSTANT, {idU32, idTwo, 2U});
      spirv::instruction(w, spirv::OP_CONSTANT, {idU32, idThree, 3U});

      for (const InterfaceVar& var : inputs)
      {
        if (var.builtIn != SPIRV_NO_BUILTIN)
          spirv::instruction(w, spirv::OP_DECORATE, {var.id, spirv::DEC_BUILT_IN, var.builtIn});
        else
          spirv::instruction(w, spirv::OP_DECORATE, {var.id, spirv::DEC_LOCATION, var.location});
        spirv::instruction(w, spirv::OP_VARIABLE,
                           {var.integerData ? idVecU : idVecF, var.id, spirv::STORAGE_INPUT});
      }

      for (const InterfaceVar& var : outputs)
      {
        if (var.builtIn != SPIRV_NO_BUILTIN)
          spirv::instruction(w, spirv::OP_DECORATE, {var.id, spirv::DEC_BUILT_IN, var.builtIn});
        else
          spirv::instruction(w, spirv::OP_DECORATE, {var.id, spirv::DEC_LOCATION, var.location});
        spirv::instruction(w, spirv::OP_VARIABLE,
                           {var.integerData ? idVecU : idVecF, var.id, spirv::STORAGE_OUTPUT});
      }

      spirv::instruction(w, spirv::OP_FUNCTION, {idVoid, idMain, 0U, idFn});

      std::vector<std::uint32_t> body;
      spirv::instruction(body, spirv::OP_LABEL, {idLabel});

      // The per-output object the component writes land in, initialised to nothing. An output the
      // program never writes holds an undefined value - said with OpUndef rather than with a zero
      // the game never asked for.
      for (std::size_t i = 0; i < outputs.size(); ++i)
      {
        const std::uint32_t vec = outputs[i].integerData ? idVecU : idVecF;
        spirv::instruction(body, spirv::OP_UNDEF, {vec, undefOutput[i]});
        spirv::instruction(body, spirv::OP_VARIABLE, {vec, localOutput[i], spirv::STORAGE_FUNCTION, undefOutput[i]});
      }

      for (std::size_t i = 0; i < inputs.size(); ++i)
        spirv::instruction(body, spirv::OP_LOAD,
                           {inputs[i].integerData ? idVecU : idVecF, loadedInput[i], inputs[i].id});

      for (const ReadValue& read : reads)
        spirv::instruction(body, spirv::OP_COMPOSITE_EXTRACT,
                           {inputs[read.inputIndex].integerData ? idU32 : idF32, read.scalarId,
                            loadedInput[read.inputIndex], read.component});

      for (const StorePlan& store : stores)
      {
        for (std::size_t lane = 0U; lane < store.lanes.size(); ++lane)
        {
          const std::uint32_t component = store.lanes[lane].first;
          const std::uint32_t componentConst = component == 0U   ? idZero
                                             : component == 1U ? idOne
                                             : component == 2U ? idTwo
                                                               : idThree;
          const bool integerData = outputs[store.outputIndex].integerData;
          const ReadValue& read = reads[store.lanes[lane].second];

          spirv::instruction(body, spirv::OP_ACCESS_CHAIN,
                             {integerData ? idPtrScalarU : idPtrScalarF, store.insertIds[lane],
                              localOutput[store.outputIndex], componentConst});
          spirv::instruction(body, spirv::OP_STORE, {store.insertIds[lane], read.scalarId});
        }

        const std::uint32_t vec = outputs[store.outputIndex].integerData ? idVecU : idVecF;
        spirv::instruction(body, spirv::OP_LOAD, {vec, loadedOutput[store.outputIndex], localOutput[store.outputIndex]});
        spirv::instruction(body, spirv::OP_STORE, {outputs[store.outputIndex].id, loadedOutput[store.outputIndex]});
      }

      spirv::instruction(body, spirv::OP_RETURN, {});
      spirv::instruction(body, spirv::OP_FUNCTION_END, {});

      w.insert(w.end(), body.begin(), body.end());

      facts.translated = true;
      return true;
    }

    // ---------------------------------------------------------------------------------------
    // The layer.
    // ---------------------------------------------------------------------------------------

    struct Layer
    {
      const VulkanDevice::Device* device = nullptr;
      VkDevice deviceHandle = VK_NULL_HANDLE;
      bool initialized = false;

      std::vector<CachedShader> cache;

      std::uint32_t hits = 0U;
      std::uint32_t misses = 0U;
      std::uint32_t modules = 0U;
      std::uint32_t refusals = 0U;
      std::uint16_t refusalOpcode = 0xFFFFU;

      // Lookups that never reached the cache because the bytecode was not a program at all: a null
      // pointer or a zero size is a caller's bug, and counting it apart from a refusal of a real
      // shader is what keeps the two from being confused in a report.
      std::uint32_t badRequests = 0U;
    };

    Layer g_Layer;

    template <typename T>
    T entry_point(const VulkanDevice::Device& device, const char* name)
    {
      if (device.getInstanceProcAddr == nullptr)
        return nullptr;

      return reinterpret_cast<T>(device.getInstanceProcAddr(device.instance, name));
    }

    std::size_t find_entry(const std::uint64_t hash, const Stage stage)
    {
      for (std::size_t i = 0; i < g_Layer.cache.size(); ++i)
        if (g_Layer.cache[i].hash == hash && g_Layer.cache[i].stage == stage)
          return i;

      return g_Layer.cache.size();
    }

    void note_refusal(const std::uint16_t opcode)
    {
      ++g_Layer.refusals;
      if (opcode != 0xFFFFU && g_Layer.refusalOpcode == 0xFFFFU)
        g_Layer.refusalOpcode = opcode;
    }

    // The names this file reports a refused opcode by, for the log and the console command. The
    // number is always printed as well: a name this table does not know never hides the number.
    const char* opcode_name(const std::uint16_t opcode)
    {
      switch (opcode)
      {
      case IO_NOP: return "nop";
      case IO_MOV: return "mov";
      case IO_DCL: return "dcl";
      case IO_TEXLD: return "texld";
      case IO_DEF: return "def";
      case IO_COMMENT: return "comment";
      case IO_END: return "end";
      default: return "an opcode this file does not name";
      }
    }

    bool create_module(CachedShader& entry, const char** error)
    {
      if (entry.module != VK_NULL_HANDLE)
        return true;

      if (!g_Layer.initialized || g_Layer.device == nullptr)
        return refuse(error, reason_text("no Vulkan device is attached, so no VkShaderModule can be made"));

      if (entry.spirv.empty())
        return refuse(error, reason_text("this entry converted to no SPIR-V words at all"));

      const auto create = entry_point<PFN_vkCreateShaderModule>(*g_Layer.device, "vkCreateShaderModule");
      if (create == nullptr)
        return refuse(error, reason_text("the loader that made this device does not export vkCreateShaderModule"));

      VkShaderModuleCreateInfo info{};
      info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
      info.codeSize = entry.spirv.size() * sizeof(std::uint32_t);

      VkResult result = create(g_Layer.device->device, &info, nullptr, &entry.module);
      log_result("vkCreateShaderModule", result);

      if (result != VK_SUCCESS || entry.module == VK_NULL_HANDLE)
      {
        entry.module = VK_NULL_HANDLE;
        return refuse(error, reason_fmt("vkCreateShaderModule answered %s for %llu words of SPIR-V", result_name_of(result),
                          static_cast<unsigned long long>(entry.spirv.size())));
      }

      ++g_Layer.modules;
      return true;
    }

    void destroy_module(CachedShader& entry)
    {
      if (entry.module == VK_NULL_HANDLE)
        return;

      if (g_Layer.device != nullptr && g_Layer.device->device != VK_NULL_HANDLE)
      {
        const auto destroy = entry_point<PFN_vkDestroyShaderModule>(*g_Layer.device, "vkDestroyShaderModule");
        if (destroy != nullptr)
          destroy(g_Layer.device->device, entry.module, nullptr);
        else
          log_value("no vkDestroyShaderModule - a shader module is being let go undestroyed");
      }

      entry.module = VK_NULL_HANDLE;
    }
  } // namespace

  // The hash cached by: FNV-1a over the program's bytes, with the stage mixed in first, because the
  // same bytes handed in as two stages are two different programs. 64 bits because a shader cache
  // that collides paints the wrong material somewhere, and a 32-bit hash over a few thousand
  // programs is a coin flip a check would never see.
  std::uint64_t BytecodeHash(const void* bytecode, const std::size_t byteCount, const Stage stage)
  {
    std::uint64_t hash = 0xCBF29CE484222325ULL;
    hash = (hash ^ static_cast<std::uint64_t>(stage)) * 0x100000001B3ULL;

    const unsigned char* bytes = static_cast<const unsigned char*>(bytecode);
    for (std::size_t i = 0U; i < byteCount; ++i)
      hash = (hash ^ static_cast<std::uint64_t>(bytes[i])) * 0x100000001B3ULL;

    return hash;
  }

  bool Init(const VulkanDevice::Device& device, const char** error)
  {
    if (device.device == VK_NULL_HANDLE)
      return refuse(error, reason_text("the device handed to the shader compiler is not a device"));

    if (device.getInstanceProcAddr == nullptr)
      return refuse(error, reason_text("the device carries no vkGetInstanceProcAddr to look the shader commands up with"));

    if (entry_point<PFN_vkCreateShaderModule>(device, "vkCreateShaderModule") == nullptr)
      return refuse(error, reason_text("the loader that made this device does not export vkCreateShaderModule"));

    if (entry_point<PFN_vkDestroyShaderModule>(device, "vkDestroyShaderModule") == nullptr)
      return refuse(error, reason_text("the loader that made this device does not export vkDestroyShaderModule"));

    if (g_Layer.device != nullptr && g_Layer.deviceHandle != device.device)
      ForgetAll(); // a device that died underneath the layer took its modules with it

    g_Layer.device = &device;
    g_Layer.deviceHandle = device.device;
    g_Layer.initialized = true;

    printf("iw4x32 vulkan shaders: attached - %s\n", CompilerHost());
    return true;
  }

  bool Init(const VulkanDevice::Device& device)
  {
    const char* error = nullptr;
    return Init(device, &error);
  }

  bool Bound()
  {
    return g_Layer.initialized;
  }

  void ForgetAll()
  {
    // The device is gone, so the handles are: the converted SPIR-V stays, because it belongs to the
    // bytecode and can be handed to the next device without another conversion.
    std::uint32_t dropped = 0U;
    for (CachedShader& entry : g_Layer.cache)
      if (entry.module != VK_NULL_HANDLE)
      {
        entry.module = VK_NULL_HANDLE;
        ++dropped;
      }

    if (dropped != 0U)
      printf("iw4x32 vulkan shaders: %u module(s) dropped with the device they belonged to\n", dropped);

    g_Layer.modules = 0U;
  }

  void Shutdown()
  {
    std::uint32_t destroyed = 0U;
    if (g_Layer.initialized && g_Layer.device != nullptr)
    {
      for (CachedShader& entry : g_Layer.cache)
        if (entry.module != VK_NULL_HANDLE)
        {
          destroy_module(entry);
          ++destroyed;
        }
    }
    else
    {
      destroyed = g_Layer.modules;
      if (destroyed != 0U)
        log_value("no device to destroy the modules of - their handles are being let go");
      for (CachedShader& entry : g_Layer.cache)
        entry.module = VK_NULL_HANDLE;
    }

    std::uint64_t words = 0ULL;
    for (const CachedShader& entry : g_Layer.cache)
      words += entry.spirv.size();

    printf("iw4x32 vulkan shaders: shutdown - %u program(s) cached, %u module(s) destroyed, %llu word(s) of "
           "SPIR-V held, %u hit(s), %u miss(es), %u refusal(s)\n",
           static_cast<unsigned>(g_Layer.cache.size()), destroyed, static_cast<unsigned long long>(words),
           g_Layer.hits, g_Layer.misses, g_Layer.refusals);

    g_Layer.cache.clear();
    g_Layer.hits = 0U;
    g_Layer.misses = 0U;
    g_Layer.modules = 0U;
    g_Layer.refusals = 0U;
    g_Layer.refusalOpcode = 0xFFFFU;
    g_Layer.badRequests = 0U;
    g_Layer.device = nullptr;
    g_Layer.deviceHandle = VK_NULL_HANDLE;
    g_Layer.initialized = false;
  }

  bool ConvertD3D9Bytecode(const void* bytecode, const std::size_t byteCount, const Stage stage,
                           std::vector<std::uint32_t>& outSpirv, ShaderFacts& outFacts, const char** error)
  {
    outSpirv.clear();
    outFacts = ShaderFacts{};
    outFacts.stage = stage;

    if (bytecode == nullptr || byteCount < 4U || (byteCount & 3U) != 0U)
    {
      ++g_Layer.badRequests;
      return refuse(error, reason_text("the shader bytes handed in are not a DWORD-aligned program"));
    }

    const std::uint64_t hash = BytecodeHash(bytecode, byteCount, stage);
    const std::size_t found = find_entry(hash, stage);
    if (found != g_Layer.cache.size())
    {
      ++g_Layer.hits;
      ++g_Layer.cache[found].uses;
      outSpirv = g_Layer.cache[found].spirv;
      outFacts = g_Layer.cache[found].facts;
      return true;
    }

    ++g_Layer.misses;

    Program program;
    if (!find_tokens(static_cast<const std::uint32_t*>(bytecode), byteCount / 4U, program, error))
    {
      note_refusal(0xFFFFU);
      log_shader("refused (no program)", hash, byteCount, stage);
      return false;
    }

    if (program.stage != stage)
    {
      note_refusal(0xFFFFU);
      return refuse(error, reason_fmt("this is a %s program, asked for as a %s one", stage_name_of(program.stage),
                        stage_name_of(stage)));
    }

    ShaderFacts facts;
    facts.stage = stage;
    facts.majorVersion = program.major;
    facts.minorVersion = program.minor;
    facts.bytecodeBytes = byteCount;
    facts.tokenWords = program.tokenWords;

    if (!walk_tokens(program, facts, error))
    {
      note_refusal(facts.stoppedAtOpcode);
      outFacts = facts; // the caller reads stoppedAtOpcode to see what the refusal was about
      printf("iw4x32 vulkan shaders: refused %s program hash 0x%016llx at %s (%u): %s\n", stage_name_of(stage),
             static_cast<unsigned long long>(hash), opcode_name(facts.stoppedAtOpcode),
             static_cast<unsigned>(facts.stoppedAtOpcode), *error);
      return false;
    }

    std::vector<std::uint32_t> spirvWords;
    if (!emit_spirv(program, facts, spirvWords, error))
    {
      note_refusal(0xFFFFU);
      printf("iw4x32 vulkan shaders: refused %s program hash 0x%016llx after reading it: %s\n", stage_name_of(stage),
             static_cast<unsigned long long>(hash), *error);
      return false;
    }

    CachedShader entry;
    entry.hash = hash;
    entry.stage = stage;
    entry.facts = facts;
    entry.spirv = std::move(spirvWords);
    entry.uses = 1U;
    g_Layer.cache.push_back(entry);

    printf("iw4x32 vulkan shaders: converted %s program hash 0x%016llx - sm %u.%u, %llu token word(s), "
           "%llu dcl, %llu inst, %u const, %u temp, %u sampler, %u vPos, %u vFace, %u a-reg, "
           "inputs 0x%X, outputs 0x%X, copies 0x%X, %llu SPIR-V word(s)\n",
           stage_name_of(stage), static_cast<unsigned long long>(hash), facts.majorVersion, facts.minorVersion,
           static_cast<unsigned long long>(facts.tokenWords), static_cast<unsigned long long>(facts.declarationCount),
           static_cast<unsigned long long>(facts.instructionCount), facts.constantCount, facts.tempCount,
           facts.samplerCount, facts.positionInputCount, facts.faceInputCount, facts.addressRegisterCount,
           facts.inputMask, facts.outputMask, facts.copyMask,
           static_cast<unsigned long long>(g_Layer.cache.back().spirv.size()));

    outSpirv = g_Layer.cache.back().spirv;
    outFacts = facts;
    return true;
  }

  VkShaderModule ShaderModuleForD3D9Bytecode(const void* bytecode, const std::size_t byteCount, const Stage stage,
                                             const char** error)
  {
    if (!g_Layer.initialized)
    {
      ++g_Layer.badRequests;
      *error = reason_text("no Vulkan device is attached to the shader compiler");
      return VK_NULL_HANDLE;
    }

    std::vector<std::uint32_t> spirvWords;
    ShaderFacts facts;
    if (!ConvertD3D9Bytecode(bytecode, byteCount, stage, spirvWords, facts, error))
      return VK_NULL_HANDLE;

    const std::uint64_t hash = BytecodeHash(bytecode, byteCount, stage);
    const std::size_t found = find_entry(hash, stage);
    if (found == g_Layer.cache.size())
    {
      *error = reason_text("the conversion cached nothing for these bytes");
      return VK_NULL_HANDLE;
    }

    if (!create_module(g_Layer.cache[found], error))
      return VK_NULL_HANDLE;

    return g_Layer.cache[found].module;
  }

  const std::vector<CachedShader>& Cache()
  {
    return g_Layer.cache;
  }

  std::uint32_t CacheEntries()
  {
    return static_cast<std::uint32_t>(g_Layer.cache.size());
  }

  std::uint32_t CacheHits()
  {
    return g_Layer.hits;
  }

  std::uint32_t CacheMisses()
  {
    return g_Layer.misses;
  }

  std::uint64_t CacheBytes()
  {
    std::uint64_t words = 0ULL;
    for (const CachedShader& entry : g_Layer.cache)
      words += entry.spirv.size();
    return words * sizeof(std::uint32_t);
  }

  std::uint32_t ModulesCreated()
  {
    return g_Layer.modules;
  }

  std::uint32_t Refusals()
  {
    return g_Layer.refusals;
  }

  std::uint16_t RefusalOpcode()
  {
    return g_Layer.refusalOpcode;
  }

  const char* RefusalOpcodeName()
  {
    return opcode_name(g_Layer.refusalOpcode);
  }

  // What converted these words. The built-in host translates the register-copy programs and refuses
  // the rest; an external DXC / glslangValidator is the route the rest takes, and premake5.lua's
  // iw4x32_shader_compiler() records one in IW4X32_SHADER_COMPILER_TOOL when a machine has it. A
  // build that found none says so here rather than letting "compiled by an external compiler" be
  // assumed - and a tool that is not running with the game is refused, because a compiler recorded
  // at build time on another box is not a compiler this client can run.
  const char* CompilerHost()
  {
#ifdef IW4X32_SHADER_COMPILER_TOOL
    const char* found = getenv("IW4X32_SHADER_COMPILER");
    if (found != nullptr && *found != '\0')
      return found;
    return IW4X32_SHADER_COMPILER_TOOL " (recorded by the build; it converts nothing until the same tool "
                                       "is running with the game)";
#else
    return "built-in host: shader model 3.0 token reader + SPIR-V writer for register-copy programs, "
           "everything else refused by opcode (no DXC or glslangValidator in this build)";
#endif
  }

  bool ExternalCompilerPresent()
  {
#ifdef IW4X32_SHADER_COMPILER_TOOL
    return true;
#else
    return false;
#endif
  }
} // namespace VulkanShaderCompiler
