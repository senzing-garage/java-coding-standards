public class Demo
{
    public Object build()
    {
        return SomeFactoryProducer.makeInstance().configureWithSettings(veryLongSetting, anotherLong).step2(g).finish();
    }
}
