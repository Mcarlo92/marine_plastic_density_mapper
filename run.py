import sys

from analysis.analysis import save_coordinates_to_csv, plot_data_single_day, plot_data
from fmask_api.f_mask import run_fmask
from masking.prediction_masker import mask_prediction, crop_f_mask, apply_threshold

sys.path.insert(0, "/acolite_api")
sys.path.insert(0, "/semantic_segmentation")
sys.path.insert(0, "/sentinel_downloader")
sys.path.insert(0, "/smooth_patches")
sys.path.insert(0, "/acolite-main/acolite")

import argparse
import os
from sentinelsat import read_geojson
from image_engineer.image_engineering import ImageEngineer
from utils.geographic_utils import get_crs
from utils.dir_management import setup_directories, clean_directories, base_path
from datetime import datetime, timedelta
import pandas as pd
from semantic_segmentation.debris_predictor import create_image_prediction
from sentinel_downloader.sentinel_loader import SentinelLoader
from multiprocessing import Pool
from dotenv import load_dotenv
from acolite_api.acolite_processor import run_acolite

load_dotenv()

# code for command line interface
if __name__ == "__main__":
    today = datetime.today().strftime("%Y%m%d")
    tomorrow = (datetime.today() + timedelta(days=1)).strftime("%Y%m%d")

    parser = argparse.ArgumentParser(description='A sentinel-2 plastic detection pipeline using the MARIDA dataset')

    subparsers = parser.add_subparsers(help='possible uses', dest='command')
    test = subparsers.add_parser('test', help='test')
    pipeline = subparsers.add_parser('full', help='run full pipeline for a given ROI')

    # full pipeline arguments
    pipeline.add_argument(
        '-start_date',
        nargs=1,
        default=[today],
        type=str,
        help='start_date for sentinel 2 full_pipeline predictions to start (YYYYmmdd)',
        dest='start_date'

    )
    pipeline.add_argument(
        '-end_date',
        nargs=1,
        default=[tomorrow],
        type=str,
        help='end_date for sentinel 2 full_pipeline predictions to end (YYYYmmdd)',
        dest="end_date"
    )
    pipeline.add_argument(
        '-cloud_percentage',
        nargs=1,
        default=[20],
        type=int,
        help='maximum cloud percentage',
        dest="cloud_percentage"
    )

    pipeline.add_argument(
        '-tile_id',
        nargs="+",
        default=None,
        help='tile_id -optional argument useful if interested in one tile. This can be used to prevent downloads of overlapping nearby tiles',
        dest="tile_id"
    )

    pipeline.add_argument(
        '-land_mask',
        action='store_true',
        help='mask land',
        dest="land_mask"
    )

    pipeline.add_argument(
        '-cloud_mask',
        action='store_true',
        help='mask cloud',
        dest="cloud_mask"
    )

    pipeline.add_argument(
        '-max_wind',
        nargs=1,
        default=None,
        dest="max_wind_speed",
        help="wind speed in MP. If not set, no wind speed check will be completed for location and date",
    )

    pipeline.add_argument(
        '-no_land_mask',
        action='store_false',
        help='false if no land in ROI',
        dest="land_mask"
    )

    # partial pipeline components
    download = subparsers.add_parser(
        'download',
        help='download sentinel-2 data'
    )
    download.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=[datetime.today().strftime("%Y%m%d")],
        help='use with --download to specify the date for data download', dest='date'
    )
    download.add_argument(
        '-cloud_percentage',
        nargs=1,
        type=str,
        default=[50],
        dest='cloud_percentage',
        help='use with --download to specify the date for data download'
    )

    # run fmask
    download = subparsers.add_parser(
        'fmask',
        help='generate f-mask from sentinel-2 data'
    )
    acolite = subparsers.add_parser(
        "acolite",
        help='complete acolite processing on SAFE files'
        )
    acolite.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=datetime.today().strftime("%Y%m%d"),
        help='date of SAFE files for processing',
        dest="date"
        )
    acolite.add_argument(
        '-tile_id',
        nargs=1,
        type=str,
        help='Tile ID',
        dest="tile_id"
    )

    combine_acolite = subparsers.add_parser(
        'combine_acolite',
        help='download sentinel-2 data'
    )
    combine_acolite.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=datetime.today().strftime("%Y%m%d"),
        help='complete acolite processing on SAFE files',
        dest="date"
    )
    combine_acolite.add_argument(
        '-tile_id',
        nargs=1,
        type=str,
        default="",
        help='complete acolite processing on SAFE files',
        dest="tile_id"
    )
    predict = subparsers.add_parser(
        'predict',
        help='make predictions on pre-existing geotiff'
    )

    predict.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=[today],
        help='complete acolite processing on SAFE files',
        dest="date"
    )

    predict.add_argument(
        '-tile_id',
        nargs=1,
        type=str,
        default=None,
        help='complete acolite processing on SAFE files',
        dest="tile_id"
    )
    mask = subparsers.add_parser(
        'mask',
        help='mask predictions using fmask for more robust cloud and land detection'
    )

    mask.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=datetime.today().strftime("%Y%m%d"),
        help='date of SAFE files for processing',
        dest="date"
        )
    mask.add_argument(
        '-tile_id',
        nargs=1,
        type=str,
        help='Tile ID',
        dest="tile_id"
    )

    mask.add_argument(
        '-land_mask',
        action='store_true',
        help='mask land',
        dest="land_mask"
    )

    mask.add_argument(
        '-cloud_mask',
        action='store_true',
        help='mask land',
        dest="cloud_mask"
    )

    mask.add_argument(
        '-no_land_mask',
        action='store_false',
        help='false if no land in ROI',
        dest="land_mask"
    )

    clean = subparsers.add_parser(
        'clean',
        help='WARNING! Removes all data associated with sentinel downloads, '
             'processing and predictions in the "data" directory tree'
    )

    predict_from_acolite = subparsers.add_parser('predict_from_acolite', help='run full pipeline for a given ROI')
    predict_from_acolite.add_argument(
        '-date',
        nargs=1,
        type=str,
        default=[today],
        help='complete acolite processing on SAFE files',
        dest="date"
    )

    predict_from_acolite.add_argument(
        '-tile_id',
        nargs=1,
        type=str,
        default=None,
        help='complete acolite processing on SAFE files',
        dest="tile_id"
    )
    predict_from_acolite.add_argument(
        '-crs',
        nargs=1,
        type=str,
        default=None,
        dest="crs"
    )
    args = parser.parse_args()
    options = vars(args)
    print(options)

    if args.command == "full":
        # ensure date path has the required directories for processing and analysis
        setup_directories()

        # get start date for data collection
        start = datetime.strptime(args.start_date[0], "%Y%m%d")

        # get end date for data collection
        end = datetime.strptime(args.end_date[0], "%Y%m%d")

        # generate dates to search, convert to strings in correct format for SciHib query
        date_generated = pd.date_range(start, end)
        dates = []
        for date in date_generated.strftime("%Y%m%d"):
            dates.append(str(date).replace("_", ""))
        print("Finding SAFE files for " + str(dates))
        if not args.max_wind_speed:
            print("no max wind speed provided, getting Sentinel products..")

        # iterate through dates, query SciHib and run pipeline
        for i in range(len(dates)):

            # one day at a time for each query
            start_date = dates[i]
            end_date = (datetime.strptime(start_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")

            # details
            user_name = os.environ.get('USER_NAME')
            password = os.environ.get('PASSWORD')

            # query SciHub and download SAFE files
            SentinelLoader(start_date=start_date, end_date=end_date, max_cloud_percentage=args.cloud_percentage, tile_id=args.tile_id, max_wind_speed=args.max_wind_speed).run()
            bundles = os.listdir(os.path.join(base_path, "data", "unprocessed"))
            print(bundles)
            # if any data to process, run acolite
            if bundles:
                if __name__ == '__main__':
                    with Pool(len(bundles)) as p:
                        print(p.map(run_acolite, bundles))
                print("processing files........")

                image_engineer = ImageEngineer(date=start_date, land_mask=args.land_mask, cloud_mask=args.cloud_mask)

                # get crs of SAFE file
                image_engineer.crs = get_crs()

                # load processed acolite rhos images (assigns file path to self.tiff_files)
                image_engineer.load_images()

                # combines processed satellite images output by acolite processor (one for each band)
                image_engineer.combine_bands()

                # merges sentinel 2 tiles into one large image covering whole region of interest
                # please note, this could be made more efficient by patching each tile, then merging the tiles.
                # However, care must be taken not to lose pixels due to cropping.
                # if using 1 or 2 sentinel tiles, it does not make much difference
                image_engineer.merge_tiles(directory=os.path.join(base_path, "data", "unmerged_geotiffs"), mode="images")

                # patch full ROI for predictions
                image_engineer.patch_image(os.path.join(base_path, "data", "merged_geotiffs",  image_engineer.id + "_" + image_engineer.date + ".tif"))

                # make predictions on image patches
                create_image_prediction()

                # merge predicted masks into one file
                #ImageEngineer.merge_tiles(directory=os.path.join(base_path, "data", "predicted_patches"), mode="masks")

                image_engineer.merge_tiles(directory=os.path.join(base_path, "data", "predicted_patches"), mode="probs")

                # run f-mask on each sentinel SAFE file
                run_fmask(os.path.join(base_path, "data", "unprocessed"))

                # merge f-masks into one large mask
                image_engineer.merge_tiles(directory=os.path.join(base_path, "data", "merged_geotiffs"), mode="clouds")

                # apply threshold
                apply_threshold(os.path.join(base_path, "data", "merged_geotiffs"), 0.99)

                # read coords for f-mask crop
                poly = read_geojson(os.path.join(base_path, "poly.geojson"))

                # crop f-mask for ROI
                crop_f_mask(image_engineer.id, image_engineer.date, poly, image_engineer.crs)

                # apply f-mask to predictions, generate and apply land-mask
                mask_prediction(id=image_engineer.id, date=image_engineer.date, land_mask=image_engineer.land_mask, cloud_mask=image_engineer.cloud_mask)

                # get plastic coordiantes and save to csv
                save_coordinates_to_csv(os.path.join(base_path, "data", "merged_geotiffs"), "prediction_masked")

                # plot single date coordinates
                plot_data_single_day(image_engineer.date)

                # clean data dirs for next iteration, save predictions and tif to historic files dir
                clean_directories(image_engineer.date)

        # plot all plastic detections
        plot_data(os.path.join(base_path, "data", "outputs"), "prediction_masked")

    if args.command == "download":
        date = args.date[0]
        print("downloading data for given date: " + date)
        # get day following for range of 1 day
        user_name = os.environ.get('USER_NAME')
        password = os.environ.get('PASSWORD')
        end_date = (datetime.strptime(date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        SentinelLoader(start_date=date, end_date=end_date, max_cloud_percentage=args.cloud_percentage).run()

    if args.command == "acolite":
        bundles = os.listdir(os.path.join(base_path, "data", "unprocessed"))
        print(bundles)
        # if any data to download and process
        if bundles:
            if __name__ == '__main__':
                print("processing SAFE files with acolite........")
                with Pool(len(bundles)) as p:
                    print(p.map(run_acolite, bundles))

    if args.command == "fmask":
        path = os.path.join(base_path, "data", "unprocessed")
        run_fmask(path)

    if args.command == "combine_acolite":

        image_engineer = ImageEngineer(date=args.date[0], id=args.tile_id[0])

        # load processed acolite rhos images (assigns file path to self.tiff_files)
        image_engineer.load_images()

        # combines processed satellite images output by acolite processor (one for each band)
        image_engineer.combine_bands()

        # merges sentinel 2 tiles into one large image covering whole region of interest
        # please note, this could be made more efficient by patching each tile, then merging the tiles.
        # However, care must be taken not to lose pixels due to cropping.
        # if using 1 or 2 sentinel tiles, it does not make much difference
        image_engineer.merge_tiles(directory=os.path.join(base_path, "data", "unmerged_geotiffs"), mode="images")

    if args.command == "predict":

        image_engineer = image_engineer(date=args.date[0], id=args.tile_id[0], crs=get_crs())
        # patch full ROI for predictions

        image_engineer.patch_image(os.path.join(base_path, "data", "merged_geotiffs",  image_engineer.id + "_" +  image_engineer.date + ".tif"))

        create_image_prediction()

        # merge predicted masks into one file
        image_engineer.merge_tiles(directory=os.path.join(base_path, "data", "predicted_patches"), mode="masks")

    if args.command == "mask":

        image_engineer = image_engineer(date=args.date[0], id=args.tile_id[0], land_mask=args.land_mask, cloud_mask=args.cloud_mask)

        # get crs from sentinel tile
        image_engineer.crs = get_crs()

        # read coords for f-mask crop
        poly = read_geojson(os.path.join(base_path, "poly.geojson"))

        # crop f-mask for ROI
        crop_f_mask(image_engineer.id,  image_engineer.date, poly, image_engineer.crs)

        # apply f-mask to predictions, generate and apply land-mask
        mask_prediction(image_engineer.id, image_engineer.date, image_engineer.land_mask, image_engineer.cloud_mask)

    if args.command == "clean":
        clean_directories(date=args.date[0])

