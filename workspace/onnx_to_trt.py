from __future__ import print_function

import argparse
import traceback
import sys
import tensorrt as trt

#sys.path.append('./')  # to run '$ python *.py' files in subdirectories
from calibrator import DataLoader, Calibrator

MAX_BATCH_SIZE = 1

def build_engine_from_onnx(model_name,
                           dtype,
                           verbose=False,
                           int8_calib=False,
                           calib_loader=None,
                           calib_cache=None,
                           dynamic_shape=False,
                           fp32_layer_names=[],
                           fp16_layer_names=[],
                           ):
    """Initialization routine."""
    if dtype == "int8":
        t_dtype = trt.DataType.INT8
    elif dtype == "fp16":
        t_dtype = trt.DataType.HALF
    elif dtype == "fp32":
        t_dtype = trt.DataType.FLOAT
    else:
        raise ValueError("Unsupported data type: %s" % dtype)

    if trt.__version__[0] < '8':
        print('Exit, trt.version should be >=8. Now your trt version is ', trt.__version__[0])

    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    if dtype == "int8" and calib_loader is None:
        print('QAT enabled!')
        network_flags = network_flags | (1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_PRECISION))

    """Build a TensorRT engine from ONNX"""
    TRT_LOGGER = trt.Logger(trt.Logger.VERBOSE) if verbose else trt.Logger()
    with trt.Builder(TRT_LOGGER) as builder, builder.create_network(flags=network_flags) as network, \
            trt.OnnxParser(network, TRT_LOGGER) as parser:
        with open(model_name, 'rb') as model:
            if not parser.parse(model.read()):
                print('ERROR: ONNX Parse Failed')
                for error in range(parser.num_errors):
                    print(parser.get_error(error))
                    return None

        print('Building an engine.  This would take a while...')
        print('(Use "--verbose" or "-v" to enable verbose logging.)')
        config = builder.create_builder_config()

        # DF: deprecation fix
        #config.max_workspace_size = 2 << 30
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30)

        if t_dtype == trt.DataType.HALF:
            config.flags |= 1 << int(trt.BuilderFlag.FP16)

        if t_dtype == trt.DataType.INT8:
            config.flags |= 1 << int(trt.BuilderFlag.INT8)
            config.flags |= 1 << int(trt.BuilderFlag.FP16)

            if int8_calib:
                config.int8_calibrator = Calibrator(calib_loader, calib_cache)
                print('Int8 calibation is enabled.')

        if dynamic_shape:
            # You can adjust the shape setting according to the actual situation
            profile = builder.create_optimization_profile()
            profile.set_shape("images", (1, 3, 640, 640), (8, 3, 640, 640), (16, 3, 640, 640))
            config.add_optimization_profile(profile)

        # DF: deprecation fix
        #engine = builder.build_engine(network, config)
        engine = builder.build_serialized_network(network, config)

        try:
            assert engine
        except AssertionError:
            _, _, tb = sys.exc_info()
            traceback.print_tb(tb)  # Fixed format
            tb_info = traceback.extract_tb(tb)
            _, line, _, text = tb_info[-1]
            raise AssertionError(
                "Parsing failed on line {} in statement {}".format(line, text)
            )

        return engine


def main():
    """Create a TensorRT engine for ONNX-based YOLO."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='enable verbose output (for debugging)')
    parser.add_argument(
        '-m', '--model', type=str, required=True,
        help=('onnx model path'))
    parser.add_argument(
        '-d', '--dtype', type=str, required=True,
        help='one type of int8, fp16, fp32')
    parser.add_argument('--dynamic-shape', action='store_true',
        help='Dynamic shape,  defer specifying some or all tensor dimensions until runtime')
    parser.add_argument(
        '--qat', action='store_true',
        help='whether the onnx model is qat; if it is, the int8 calibrator is not needed')
    # If enable int8(not post-QAT model), then set the following
    parser.add_argument('--img-size', type=int,
                        default=640, help='image size of model input')
    parser.add_argument('--batch-size', type=int,
                        default=128, help='batch size for training: default 64')
    parser.add_argument('--num-calib-batch', default=6, type=int,
                        help='Number of batches for calibration')
    parser.add_argument('--calib-img-dir', default='./datasets/coco/images/train2017', type=str,
                        help='Number of batches for calibration')
    parser.add_argument('--calib-cache', default='./calibration.cache', type=str,
                        help='Path of calibration cache')
    parser.add_argument('--calib-method', default='minmax', type=str,
                        help='Calibration method')

    args = parser.parse_args()


    if args.dtype == "int8" and not args.qat:
        calib_loader = DataLoader(args.batch_size, args.num_calib_batch, args.calib_img_dir,
                                  args.img_size, args.img_size)
        engine = build_engine_from_onnx(args.model, args.dtype, args.verbose,
                              int8_calib=True, calib_loader=calib_loader, calib_cache=args.calib_cache,
                              dynamic_shape=args.dynamic_shape)
    else:
        engine = build_engine_from_onnx(args.model, args.dtype, args.verbose,
                              dynamic_shape=args.dynamic_shape)

    if engine is None:
        raise SystemExit('ERROR: failed to build the TensorRT engine!')

    engine_path = args.model.replace('.onnx',
        f'-int8-{args.batch_size}-{args.num_calib_batch}-{args.calib_method}.engine'
        if args.dtype == 'int8' and not args.qat else
        '.engine')

    with open(engine_path, 'wb') as f:
        f.write(engine)
    print(f'Serialized the TensorRT engine to file: {engine_path}')


if __name__ == '__main__':
    main()
