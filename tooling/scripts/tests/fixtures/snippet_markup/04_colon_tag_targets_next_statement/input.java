public class Demo
{
    void run()
    {
        // @highlight substring="getVirtualEntity" :
        String virtualEntity = engine.getVirtualEntity(recordKeys, SZ_VIRTUAL_ENTITY_DEFAULT_FLAGS);

        // an ordinary comment ending in a colon targets nothing:
        String virtualEntity = engine.getVirtualEntity(recordKeys, SZ_VIRTUAL_ENTITY_DEFAULT_FLAGS);
    }
}
