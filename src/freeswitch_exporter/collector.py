"""
Prometheus collecters for FreeSWITCH.
"""
# pylint: disable=too-few-public-methods

import asyncio
import itertools
import json

#from contextlib import asynccontextmanager

from asgiref.sync import async_to_sync
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily

from freeswitch_exporter.esl import ESL

import xml.etree.ElementTree as ET


class ESLProcessInfo():
    """
    Process info async collector
    """

    def __init__(self, esl: ESL):
        self._esl = esl

    async def collect(self):
        """
        Collects FreeSWITCH process info metrics.
        """

        (_, result) = await self._esl.send(
            'api json {"command" : "status", "data" : ""}')
        response = json.loads(result).get('response', {})

        test_metric = GaugeMetricFamily(
            'freeswitch_test',
            'FreeSWITCH test metric')
        test_metric.add_metric([], 12)

        process_info_metric = GaugeMetricFamily(
            'freeswitch_info',
            'FreeSWITCH info',
            labels=['version'])
        if 'version' in response:
            process_info_metric.add_metric([response['version']], 1)

        process_status_metric = GaugeMetricFamily(
            'freeswitch_up',
            'FreeSWITCH ready status',
        )
        if 'systemStatus' in response:
            status = int(response['systemStatus'] == 'ready')
            process_status_metric.add_metric([], status)

        process_memory_metric = GaugeMetricFamily(
            'freeswitch_stack_bytes',
            'FreeSWITCH stack size',
        )
        if 'stackSizeKB' in response:
            memory = response['stackSizeKB'].get('current', 0)
            process_memory_metric.add_metric([], memory * 1024)

        process_session_metrics = []
        if 'sessions' in response:
            for metric in ['total', 'active', 'limit']:
                process_session_metric = GaugeMetricFamily(
                    f'freeswitch_session_{metric}',
                    f'FreeSWITCH {metric} number of sessions',
                )

                value = response['sessions'].get('count', {}).get(metric, 0)
                process_session_metric.add_metric([], value)

                process_session_metrics.append(process_session_metric)

        return itertools.chain([
            process_info_metric,
            process_status_metric,
            process_memory_metric
        ], process_session_metrics)

class ESLSofiaInfo():
    """
    Sofia info async collector
    """

    def __init__(self, esl: ESL):
        self._esl = esl

    async def collect(self):
        """
        Collects FreeSWITCH Sofia module metrics.
        """

        """
        Profile metrics
        """
        (_, result) = await self._esl.send("api sofia xmlstatus")
        tree = ET.fromstring(result)

        profiles_state = {}
        for profile in tree.iter("profile"):
            profile_name = profile.find("name").text
            profile_state = profile.find("state").text
            if profile_name not in profiles_state:
                profiles_state[profile_name] = 0

            if 'RUNNING' in profile_state:
                profiles_state[profile_name] += 1
            else:
                profiles_state[profile_name] -= 1

        profile_metrics = {
            'calls-in': GaugeMetricFamily(
                'freeswitch_sofia_profile_calls_in',
                'Total number of calls coming in via the profile',
                labels=['name']),
            'calls-out': GaugeMetricFamily(
                'freeswitch_sofia_profile_calls_out',
                'Total number of calls coming out via the profile',
                labels=['name']),
            'failed-calls-in': GaugeMetricFamily(
                'freeswitch_sofia_profile_failed_calls_in',
                'Total number of failed calls coming in via the profile',
                labels=['name']),
            'failed-calls-out': GaugeMetricFamily(
                'freeswitch_sofia_profile_failed_calls_out',
                'Total number of failed calls coming out via the profile',
                labels=['name']),
            'registrations': GaugeMetricFamily(
                'freeswitch_sofia_profile_registrations',
                'Total number of registrations on profile',
                labels=['name']),
        }

        profile_up_metric = GaugeMetricFamily('freeswitch_sofia_profile_up', 'Shows, if gateway is up', labels=['name'])
        for profile_name, state in profiles_state.items():
            profile_up_metric.add_metric([profile_name], state)
            (_, profile_result) = await self._esl.send(f'api sofia xmlstatus profile {profile_name}')
            profile = ET.fromstring(profile_result).find('profile-info')
            for key, profile_metric in profile_metrics.items():
                value = int(profile.find(key).text)
                profile_metric.add_metric([profile_name], value)

        """
        Gateway metrics
        """
        gateway_metrics = {
            'calls-in': GaugeMetricFamily(
                'freeswitch_sofia_gateway_calls_in',
                'Total number of calls coming in via the gateway',
                labels=['name']),
            'calls-out': GaugeMetricFamily(
                'freeswitch_sofia_gateway_calls_out',
                'Total number of calls coming out via the gateway',
                labels=['name']),
            'failed-calls-in': GaugeMetricFamily(
                'freeswitch_sofia_gateway_failed_calls_in',
                'Total number of failed calls coming in via the gateway',
                labels=['name']),
            'failed-calls-out': GaugeMetricFamily(
                'freeswitch_sofia_gateway_failed_calls_out',
                'Total number of failed calls coming out via the gateway',
                labels=['name'])
        }

        gateway_up_metric = GaugeMetricFamily('freeswitch_sofia_gateway_up', 'Shows, if gateway is up', labels=['name'])
        for gateway in tree.iter("gateway"):
            gateway_name = gateway.find("name").text
            (_, gateway_result) = await self._esl.send(f'api sofia xmlstatus gateway {gateway_name}')
            gateway_data = ET.fromstring(gateway_result)

            gateway_up_metric.add_metric([gateway_name], int(gateway_data.find('status').text == "UP"))

            for key, gateway_metric in gateway_metrics.items():
                value = int(gateway_data.find(key).text)
                gateway_metric.add_metric([gateway_name], value)

        return itertools.chain([gateway_up_metric, profile_up_metric], gateway_metrics.values(), profile_metrics.values())


class ESLChannelInfo():
    """
    Channel info async collector
    """

    def __init__(self, esl: ESL):
        self._esl = esl

    async def collect(self):
        """
        Collects channel metrics.
        """

        channel_metrics = {
            'variable_rtp_audio_in_raw_bytes': GaugeMetricFamily(
                'rtp_audio_in_raw_bytes_total',
                'Total number of bytes received via this channel.',
                labels=['id']),
            'variable_rtp_audio_out_raw_bytes': GaugeMetricFamily(
                'rtp_audio_out_raw_bytes_total',
                'Total number of bytes sent via this channel.',
                labels=['id']),
            'variable_rtp_audio_in_media_bytes': GaugeMetricFamily(
                'rtp_audio_in_media_bytes_total',
                'Total number of media bytes received via this channel.',
                labels=['id']),
            'variable_rtp_audio_out_media_bytes': GaugeMetricFamily(
                'rtp_audio_out_media_bytes_total',
                'Total number of media bytes sent via this channel.',
                labels=['id']),
            'variable_rtp_audio_in_packet_count': GaugeMetricFamily(
                'rtp_audio_in_packets_total',
                'Total number of packets received via this channel.',
                labels=['id']),
            'variable_rtp_audio_out_packet_count': GaugeMetricFamily(
                'rtp_audio_out_packets_total',
                'Total number of packets sent via this channel.',
                labels=['id']),
            'variable_rtp_audio_in_media_packet_count': GaugeMetricFamily(
                'rtp_audio_in_media_packets_total',
                'Total number of media packets received via this channel.',
                labels=['id']),
            'variable_rtp_audio_out_media_packet_count': GaugeMetricFamily(
                'rtp_audio_out_media_packets_total',
                'Total number of media packets sent via this channel.',
                labels=['id']),
            'variable_rtp_audio_in_skip_packet_count': GaugeMetricFamily(
                'rtp_audio_in_skip_packets_total',
                'Total number of inbound packets discarded by this channel.',
                labels=['id']),
            'variable_rtp_audio_out_skip_packet_count': GaugeMetricFamily(
                'rtp_audio_out_skip_packets_total',
                'Total number of outbound packets discarded by this channel.',
                labels=['id']),
            'variable_rtp_audio_in_jitter_packet_count': GaugeMetricFamily(
                'rtp_audio_in_jitter_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_in_dtmf_packet_count': GaugeMetricFamily(
                'rtp_audio_in_dtmf_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_out_dtmf_packet_count': GaugeMetricFamily(
                'rtp_audio_out_dtmf_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_in_cng_packet_count': GaugeMetricFamily(
                'rtp_audio_in_cng_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_out_cng_packet_count': GaugeMetricFamily(
                'rtp_audio_out_cng_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_in_flush_packet_count': GaugeMetricFamily(
                'rtp_audio_in_flush_packets_total',
                'Total number of ? packets in this channel.',
                labels=['id']),
            'variable_rtp_audio_in_largest_jb_size': GaugeMetricFamily(
                'rtp_audio_in_jitter_buffer_bytes_max',
                'Largest jitterbuffer size in this channel.',
                labels=['id']),
            'variable_rtp_audio_in_jitter_min_variance': GaugeMetricFamily(
                'rtp_audio_in_jitter_seconds_min',
                'Minimal jitter in seconds.',
                labels=['id']),
            'variable_rtp_audio_in_jitter_max_variance': GaugeMetricFamily(
                'rtp_audio_in_jitter_seconds_max',
                'Maximum jitter in seconds.',
                labels=['id']),
            'variable_rtp_audio_in_jitter_loss_rate': GaugeMetricFamily(
                'rtp_audio_in_jitter_loss_rate',
                'Ratio of lost packets due to inbound jitter.',
                labels=['id']),
            'variable_rtp_audio_in_jitter_burst_rate': GaugeMetricFamily(
                'rtp_audio_in_jitter_burst_rate',
                'Ratio of packet bursts due to inbound jitter.',
                labels=['id']),
            'variable_rtp_audio_in_mean_interval': GaugeMetricFamily(
                'rtp_audio_in_mean_interval_seconds',
                'Mean interval in seconds of inbound packets',
                labels=['id']),
            'variable_rtp_audio_in_flaw_total': GaugeMetricFamily(
                'rtp_audio_in_flaw_total',
                'Total number of flaws detected in the channel',
                labels=['id']),
            'variable_rtp_audio_in_quality_percentage': GaugeMetricFamily(
                'rtp_audio_in_quality_percent',
                'Audio quality in percent',
                labels=['id']),
            'variable_rtp_audio_in_mos': GaugeMetricFamily(
                'rtp_audio_in_quality_mos',
                'Audio quality as Mean Opinion Score, (between 1 and 5)',
                labels=['id']),
            'variable_rtp_audio_rtcp_octet_count': GaugeMetricFamily(
                'rtcp_audio_bytes_total',
                'Total number of rtcp bytes in this channel.',
                labels=['id']),
            'variable_rtp_audio_rtcp_packet_count': GaugeMetricFamily(
                'rtcp_audio_packets_total',
                'Total number of rtcp packets in this channel.',
                labels=['id']),
        }

        channel_info_metric = GaugeMetricFamily(
            'rtp_channel_info',
            'FreeSWITCH RTP channel info',
            labels=['id', 'name', 'user_agent'])

        active_calls_metric = GaugeMetricFamily(
            'freeswitch_active_calls_count',
            'FreeSWITCH total active calls count')

        millisecond_metrics = [
            'variable_rtp_audio_in_jitter_min_variance',
            'variable_rtp_audio_in_jitter_max_variance',
            'variable_rtp_audio_in_mean_interval',
        ]

        (_, result) = await self._esl.send('api show calls as json')
        calls = json.loads(result)
        active_calls_metric.add_metric([], calls['row_count'])
        for row in calls.get('rows', []):
            uuid = row['uuid']

            await self._esl.send(f'api uuid_set_media_stats {uuid}')
            (_, result) = await self._esl.send(f'api uuid_dump {uuid} json')
            channelvars = json.loads(result)

            label_values = [uuid]
            for key, metric_value in channelvars.items():
                if key in millisecond_metrics:
                    metric_value = float(metric_value) / 1000.
                if key in channel_metrics:
                    channel_metrics[key].add_metric(
                        label_values, metric_value)

            user_agent = channelvars.get('variable_sip_user_agent', 'Unknown')
            channel_info_label_values = [uuid, row['name'], user_agent]
            channel_info_metric.add_metric(
                channel_info_label_values, 1)

        return itertools.chain(
            channel_metrics.values(),
            [channel_info_metric, active_calls_metric])


class ChannelCollector():
    """
    Collects channel statistics.

    # HELP freeswitch_version_info FreeSWITCH version info
    # TYPE freeswitch_version_info gauge
    freeswitch_version_info{release="15",repoid="7599e35a",version="4.4"} 1.0
    """

    def __init__(self, host, port, password):
        self._host = host
        self._port = port
        self._password = password

    # @asynccontextmanager
    # async def _connect(self):
    #     reader, writer = await asyncio.open_connection(self._host, self._port)
    #     try:
    #         esl = ESL(reader, writer)
    #         await esl.initialize()
    #         await esl.login(self._password)
    #         yield esl
    #     finally:
    #         writer.close()
    #         await writer.wait_closed()

    @async_to_sync
    async def collect(self):  # pylint: disable=missing-docstring
        async with EslAsyncContextManager(self._host, self._port, self._password) as esl:
            return itertools.chain(
                await ESLProcessInfo(esl).collect(),
                await ESLChannelInfo(esl).collect(),
                await ESLSofiaInfo(esl).collect())

class EslAsyncContextManager(object):
    def __init__(self, host, port, password):
        self._host = host
        self._port = port
        self._password = password
        self._reader = {}
        self._writer = {}

    async def __aenter__(self):
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        esl = ESL(self._reader, self._writer)
        await esl.initialize()
        await esl.login(self._password)
        return esl

    async def __aexit__(self, exc_type, exc_value, traceback):
        self._writer.close()
        #await self._writer.wait_closed()

def collect_esl(config, host):
    """Scrape a host and return prometheus text format for it (asinc)"""

    port = config.get('port', 8021)
    password = config.get('password', 'ClueCon')

    registry = CollectorRegistry()
    registry.register(ChannelCollector(host, port, password))
    return generate_latest(registry)
